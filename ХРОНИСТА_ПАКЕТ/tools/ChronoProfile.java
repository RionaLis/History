// =====================================================================
//  ChronoProfile.java — профиль Planetiler для «Хронисты»
// =====================================================================
//  Превращает ОДИН GeoJSON эпохи в ОДИН файл .pmtiles.
//
//  Что происходит:
//    • имя слоя внутри тайла берётся из свойства "_layer"
//      (borders / cultures / routes / hydro / places / events);
//    • ТОЧКИ выпускаются через features.point(), полигоны и линии —
//      через features.anyGeometry(). Это не стилистика: anyGeometry()
//      точки молча теряет, см. комментарий в processFeature;
//    • все остальные свойства (name_ru, wikidata, color, article, start,
//      end, source…) ЗАПЕКАЮТСЯ внутрь тайла. Сайт читает их прямо из
//      свойства объекта и не подгружает ничего извне — ни названий,
//      ни цветов, ни ссылок на статьи;
//    • служебные свойства, начинающиеся с "_", в тайлы не попадают.
//
//  ---------------------------------------------------------------
//  ЗАМЕРЫ, полученные на демо-эпохе «323 г. до н.э.»
//  (88 объектов, 13 916 вершин, исходный GeoJSON 319 КБ):
//
//      maxzoom   вес .pmtiles
//      z0–4        175 КБ
//      z0–5        335 КБ      <-- мировой снимок, экономный
//      z0–6        692 КБ      <-- мировой снимок, рекомендуемый
//      z0–7      1 486 КБ
//      z0–8      3 325 КБ
//
//  КАЖДЫЙ ЛИШНИЙ ЗУМ УДВАИВАЕТ ВЕС. А допуск упрощения
//  (setPixelTolerance) почти ничего не даёт: 1.0 → 4.0 пикселя
//  уменьшает файл всего на 11%.
//
//  Вывод для архитектуры: мировой снимок держим на maxzoom 5–6,
//  а детальность «улиц и Колизея» делаем ОТДЕЛЬНЫМ региональным
//  файлом (maps/poi/rome/, maxzoom 10–14), который подгружается
//  только при приближении. Так и вес под контролем, и детализация есть.
//  ---------------------------------------------------------------
//
//  Сборка и запуск (нужна Java 21 или новее — проверено на Temurin 21.0.12):
//    javac -cp planetiler.jar ChronoProfile.java
//    java  -cp "planetiler.jar:." ChronoProfile \
//          --input=compiled.geojson --output=era-bc323.pmtiles \
//          --minzoom=0 --maxzoom=6 --force
//
//  planetiler.jar (89 МБ) скачивается один раз:
//    https://github.com/onthegomap/planetiler/releases/latest
//  В репозиторий его НЕ коммитим — в GitHub Actions он скачивается сам.
//
//  Примечание: при компиляции javac может выдать
//  «error while writing NullProfile: null» — это не мешает: файл
//  ChronoProfile.class создаётся и всё работает. Лечится ключом -d
//  (отдельная папка для классов), что и делает tools/make_tiles.py.
// =====================================================================

import com.onthegomap.planetiler.FeatureCollector;
import com.onthegomap.planetiler.Planetiler;
import com.onthegomap.planetiler.Profile;
import com.onthegomap.planetiler.config.Arguments;
import com.onthegomap.planetiler.geo.GeometryException;
import com.onthegomap.planetiler.reader.SourceFeature;
import java.nio.file.Path;

public class ChronoProfile implements Profile {

  private final Planetiler planetiler;

  public ChronoProfile(Planetiler planetiler) {
    this.planetiler = planetiler;
  }

  @Override public String name() { return "chrono"; }
  @Override public String description() {
    return "Хрониста: исторические границы, города и события";
  }

  @Override
  public void processFeature(SourceFeature sf, FeatureCollector features) {
    // Битую геометрию пропускаем молча, чтобы один кривой полигон
    // не ронял сборку всей эпохи.
    try {
      if (sf.worldGeometry() == null) return;
    } catch (GeometryException e) {
      return;
    }

    var tags = sf.tags();

    Object layer = tags.get("_layer");
    String layerName = (layer == null || layer.toString().isBlank())
        ? "borders" : layer.toString();

    // ---------------------------------------------------------------
    // КРИТИЧНО: точки надо выпускать через features.point(), а не
    // через features.anyGeometry(). Проверено на Planetiler v0.10.2:
    // на GeoJSON из ОДНОЙ точки anyGeometry() не выдаёт НИЧЕГО —
    // в .pmtiles оказывается vector_layers: [] и ни одного тайла.
    // Тот же файл через point() + setMinZoom(0) даёт слой «places»
    // и тайл z3 весом 102 байта.
    //
    // Симптом очень тихий: сборка проходит без ошибок и предупреждений,
    // вес файла выглядит правдоподобно (полигоны-то на месте), а города
    // и события на карте просто не появляются. Именно так в демо-эпохе
    // bc323 пропали 2 города и 5 событий, а в bc2400 — все 80 городов.
    // ---------------------------------------------------------------
    FeatureCollector.Feature out = sf.isPoint()
        ? features.point(layerName)
        : features.anyGeometry(layerName);

    if (sf.isPoint()) {
      // У точки нет размера в пикселях, поэтому setMinPixelSize к ней
      // неприменим — а вот minzoom обязателен, иначе она не появится.
      out.setMinZoom(0);
    } else {
      // 0.05 пикселя = «не выбрасывать почти ничего».
      // Поднимать бессмысленно: на вес влияет maxzoom, а не это (см. замеры).
      out.setMinPixelSize(0.05);
      out.setPixelTolerance(1.0);
    }

    for (var e : tags.entrySet()) {
      String k = e.getKey();
      Object v = e.getValue();
      if (k == null || k.startsWith("_") || v == null) continue;
      if (v instanceof Number || v instanceof Boolean || v instanceof String) {
        out.setAttr(k, v);
      }
    }
  }

  public static void main(String[] args) {
    Arguments a = Arguments.fromArgs(args);

    String inArg  = a.getString("input",  "входной GeoJSON эпохи", "compiled.geojson");
    String outArg = a.getString("output", "выходной .pmtiles",     "out.pmtiles");
    String src    = a.getString("source", "имя источника",         "chrono");
    Path out = Path.of(outArg);

    Planetiler.create(a)
        .addGeoJsonSource(src, Path.of(inArg))
        .overwriteOutput(out)          // формат определяется расширением: .pmtiles
        .setProfile(ChronoProfile::new)
        .run();
  }
}
