# QuickerAtlas: an atlas of Québec's bridges

**[▶ Open the atlas](https://acfakkoh.github.io/QuickerAtlasOA/)**. It's free, needs no account and runs in the browser. *[Version française](README.fr.md)*

![QuickerAtlas: map, structure sheet and LiDAR profile](docs/capture.jpg)

QuickerAtlas puts the **≈ 11,700 structures** of Québec's Ministry of Transportation (MTMD) on one fast map:
bridges, culverts, retaining walls and tunnels. The interface is in French, like the source inventory.

## What it does

- **Search and filter** by name, road, river, town, region, bridge type, year, length, condition index (ICG),
  load or height restriction.
- **Open a structure sheet** with its photo, dimensions, condition, last inspection, traffic, and links to the
  official MTMD sheet and inspection report, plus Wikipedia for about 160 well-known bridges.
- **Switch views** with the tab bar: map, CSV-exportable list, clickable statistics, a photo gallery (one structure
  at a time), "what's new" (changes between data updates and recent inspections), or the list of **notable bridges
  of Canada** (Wikipedia): gold stars on the map, kept out of filters and statistics.
- **Add layers**: road and rail networks, rivers, geotechnical boreholes, seismic hazard and site classes, MTMD
  spring-thaw zones, other bridges outside the MTMD inventory (forest, municipal…), and the Montréal and Sherbrooke
  city inventories. The **Masquer** button under "Couches" hides every structure point to read a layer on its own.
- **Run engineering tools** from a structure sheet. The LiDAR profile computes the clearance under the deck and the
  road grades from 1 m elevation models, computed live in your browser (inset above). The river tool shows flows at
  the bridge. The seismic tool shows the National Building Code hazard.

Filters live in the URL, so copying the link shares exactly what you see.

## Data

Only **open data**: MTMD structure inventory and Données Québec (CC-BY 4.0), Natural Resources Canada LiDAR,
OpenStreetMap, MRNF, NBC 2020, Wikipedia (CC BY-SA) and Wikidata (CC0). It is refreshed periodically, and the data date is shown in the atlas header.

> Personal, independent project, **not affiliated with the MTMD**. Values are for exploration and learning only;
> the atlas asks you to acknowledge this at each start. For any decision, rely on the Ministry's official records
> and current standards. Do not use it for design, construction or asset management.

---

Developers: data pipeline, sources and architecture are in [docs/TECHNIQUE.md](docs/TECHNIQUE.md) (French).
The repository and web address keep their original name, `QuickerAtlasOA`.
Author: Anthony Chéruel.
