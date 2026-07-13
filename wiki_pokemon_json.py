#!/usr/bin/env python3
"""
Generate Mirror Gold Pokémon wiki pages from the merged per-species JSON.

Expected JSON shape, per species key:
{
  "SPECIES_ARCANINE_HISUIAN": {
    "SpeciesData": {...},
    "Learnsets": {...},
    "Evolutions": {"To": [...], "From": [...]},
    "AlternateForms": [...],
    "Encounters": [...],
    "BaseSpecies": "SPECIES_ARCANINE"
  }
}

This replaces wiki_pokemon_c.py for Pokémon pages/index generation when you
already have species data, learnsets, evos, alternate forms, and encounters
merged into one JSON file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections import OrderedDict, defaultdict
from html import escape
from pathlib import Path
from typing import Any, Iterable


METHOD_MAP = {
    "EVO_LEVEL": "level up to",
    "EVO_ITEM": "using",
    "EVO_ITEM_DAY": "held item (day level 25+)",
    "EVO_ITEM_NIGHT": "held item (night level 25+)",
    "EVO_HAPPINESS": "high friendship",
    "EVO_HAPPINESS_DAY": "high friendship during the day",
    "EVO_HAPPINESS_NIGHT": "high friendship at night",
    "EVO_TRADE": "trade",
    "EVO_TRADE_ITEM": "trade while holding",
    "EVO_MOVE": "level up knowing",
    "EVO_STONE": "stone (level 25+)",
    "EVO_NONE": "No evolution",
}

STAT_FIELDS = [
    ("hp", "HP"),
    ("attack", "Attack"),
    ("defense", "Defense"),
    ("spAttack", "Sp. Atk"),
    ("spDefense", "Sp. Def"),
    ("speed", "Speed"),
]


# ---------- constant/display helpers ----------

def species_no_prefix(species: str | None) -> str:
    if not species:
        return ""
    return species.replace("SPECIES_", "")


def species_href(species_no_prefix_value: str) -> str:
    return f"./{species_no_prefix_value.lower()}.html"


def pretty_const(value: Any, prefixes: str | Iterable[str] = ()) -> str:
    """Turn ITEM_FIRE_STONE / MOVE_THUNDER_FANG / TYPE_FIRE into readable text."""
    if value is None:
        return ""
    s = str(value)
    if isinstance(prefixes, str):
        prefixes = (prefixes,)
    for prefix in prefixes:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.replace("_", " ").title()


def pretty_species(species_const_or_no_prefix: str) -> str:
    return pretty_const(species_no_prefix(species_const_or_no_prefix))


def encounter_display_name(encdata: str) -> str:
    """Match the old helper's ENCDATA_* display names."""
    s = encdata.replace("ENCDATA_", "")
    if s.startswith("UNUSED"):
        return s.replace("_", " ")
    # Drop map-code prefix: T20_, R29_, D15R0102_, W40_, R16R0301_, etc.
    s = re.sub(r"^[A-Z]\d+(?:R\d+)?_", "", s)
    s = "ROUTE_01" if s == "ROUTE_1" else s
    return s.replace("_", " ").title().replace("Mt ", "Mt. ").replace("S S ", "S.S. ")


def stat_color(value: int) -> str:
    if value <= 50:
        return "red"
    if value <= 80:
        return "orange"
    if value <= 100:
        return "yellow"
    if value <= 120:
        return "limegreen"
    if value <= 150:
        return "green"
    return "blue"


def render_stat_bar(label: str, value: int) -> str:
    if label not in ["HP", "Attack", "Defense", "Speed", "Sp. Atk", "Sp. Def"]:
        return ""
    width_pct = min(int((value / 180) * 100), 100)
    return f"""
    <div class="stat-bar">
        <span class="label">{escape(label)}</span>
        <div class="bar-bg">
            <div class="bar-fill" style="width: {width_pct}%; background-color: {stat_color(value)};">{value}</div>
        </div>
    </div>
    """


# ---------- JSON normalization ----------

def load_species_json(path: Path) -> OrderedDict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f, object_pairs_hook=OrderedDict)
    if not isinstance(raw, dict):
        raise ValueError(f"Top-level JSON must be an object: {path}")
    raw.pop("SPECIES_NONE", None)
    return raw


def get_base_stats(entry: dict[str, Any]) -> OrderedDict[str, int]:
    base = (
        entry.get("SpeciesData", {})
        .get("speciesData", {})
        .get("baseStats", {})
    )
    out: OrderedDict[str, int] = OrderedDict()
    for field, label in STAT_FIELDS:
        try:
            out[label] = int(base[field])
        except Exception:
            pass
    return out


def get_types(entry: dict[str, Any]) -> list[str]:
    raw = entry.get("SpeciesData", {}).get("speciesData", {}).get("types", []) or []
    types = [str(t).replace("TYPE_", "") for t in raw if str(t) != "TYPE_NONE"]
    if len(types) == 2 and types[0] == types[1]:
        types = [types[0]]
    return types


def get_abilities(entry: dict[str, Any]) -> list[str]:
    raw = entry.get("SpeciesData", {}).get("speciesData", {}).get("abilities", []) or []

    abilities = [
        str(a).replace("ABILITY_", "")
        for a in raw
        if str(a) not in {"ABILITY_NONE", "0", "None"}
    ]

    return list(dict.fromkeys(abilities))


def move_name(move_const: str) -> str:
    return pretty_const(move_const, "MOVE_")


def item_or_param_name(param: Any) -> str:
    if param is None:
        return ""
    s = str(param)
    if s.upper() in {"0", "NONE", "ITEM_NONE", "MOVE_NONE", "SPECIES_NONE", "EVO_NONE"}:
        return ""
    return pretty_const(s, ("ITEM_", "MOVE_", "ABILITY_", "SPECIES_", "TYPE_"))


# ---------- encounters/index ----------

def encounter_label(row: dict[str, Any]) -> str:
    method = str(row.get("Method", "Unknown"))
    time = row.get("Time")

    # Old C generator displayed land encounter buckets as Morning/Day/Night.
    if method == "Walk" and time:
        label = str(time)
    elif time:
        label = f"{method} ({time})"
    else:
        label = method

    # if "Level" in row and row["Level"] is not None:
    #     label += f" Lv. {row['Level']}"
    # elif "MinLevel" in row and "MaxLevel" in row:
    #     mn, mx = row.get("MinLevel"), row.get("MaxLevel")
    #     label += f" Lv. {mn}" if mn == mx else f" Lv. {mn}-{mx}"

    # slots = row.get("Slots")
    # if slots:
    #     label += " Slot" + ("s" if len(slots) != 1 else "") + f" {', '.join(map(str, slots))}"
    return label


def build_species_locations(data: dict[str, dict[str, Any]]) -> dict[str, OrderedDict[str, set[str]]]:
    species_locations: dict[str, OrderedDict[str, set[str]]] = defaultdict(OrderedDict)
    for species_const, entry in data.items():
        species = species_no_prefix(species_const)
        for enc in entry.get("Encounters", []) or []:
            loc_const = enc.get("Location")
            if not loc_const:
                continue
            area = encounter_display_name(str(loc_const))
            species_locations[species].setdefault(area, set()).add(encounter_label(enc))
    return species_locations


def build_area_index(data: dict[str, dict[str, Any]]) -> tuple[dict[str, set[str]], list[str]]:
    area_to_species: dict[str, set[str]] = defaultdict(set)
    area_order: list[str] = []
    for species_const, entry in data.items():
        species = species_no_prefix(species_const)
        for enc in entry.get("Encounters", []) or []:
            loc_const = enc.get("Location")
            if not loc_const:
                continue
            area = encounter_display_name(str(loc_const))
            if area not in area_order:
                area_order.append(area)
            area_to_species[area].add(species)
    return area_to_species, area_order


def render_species_locations_grouped(species_location_map: dict[str, OrderedDict[str, set[str]]], species: str) -> str:
    areas = species_location_map.get(species, {})
    if not areas:
        return "<p><em>Not found in the wild.</em></p>"
    html: list[str] = []
    for area, methods in areas.items():
        html.append(f"<h4 class='center'>{escape(area)}</h4>")
        html.append("<ul class='center'>")
        for method in sorted(methods):
            html.append(f"  <li>{escape(method)}</li>")
        html.append("</ul>")
    return "\n".join(html)


def generate_pokemon_area_index(data: OrderedDict[str, dict[str, Any]], output_path: Path) -> None:
    species_list = [species_no_prefix(s) for s in data.keys()]
    species_order = {species: i for i, species in enumerate(species_list)}
    area_to_species, area_order = build_area_index(data)

    wild_species = set().union(*area_to_species.values()) if area_to_species else set()
    other_species = [s for s in species_list if s not in wild_species and s != "NONE"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <title>Mirror Gold Pokédex Index</title>
  <link rel='stylesheet' href='../style.css'>
</head>
<body>
  <h1 class='center'>Mirror Gold Pokédex</h1>
  <h3 class='center'><a href='../index.html'>Back to Wiki Index</a></h3>
  <div class='center'><input type='text' id='searchBox' class='center' placeholder='Search Pokémon or areas...' onkeyup='filterList()' /></div>
""")
        for area in area_order:
            mons = sorted(area_to_species.get(area, set()), key=lambda m: species_order.get(m, 10**9))
            if not mons:
                continue
            f.write(f"<h2 class='center'>{escape(area)}</h2>\n<ul class='pokemonList'>\n")
            for mon in mons:
                f.write(f"    <li class='center'><a href='{species_href(mon)}'>{escape(mon)}</a></li>\n")
            f.write("</ul>\n")

        if other_species:
            f.write("<h2 class='center'>NOT FOUND IN THE WILD / SPECIAL</h2>\n<ul class='pokemonList'>\n")
            for mon in other_species:
                f.write(f"    <li class='center'><a href='{species_href(mon)}'>{escape(mon)}</a></li>\n")
            f.write("</ul>\n")

        f.write("""
<script>
function filterList() {
    const input = document.getElementById("searchBox").value.toUpperCase();
    const sections = document.querySelectorAll("h2");
    sections.forEach(section => {
        const area = section.textContent.toUpperCase();
        const list = section.nextElementSibling;
        const items = list.getElementsByTagName("li");
        let anyVisible = false;
        for (let i = 0; i < items.length; i++) {
            const a = items[i].getElementsByTagName("a")[0];
            const name = a.textContent || a.innerText;
            const match = name.toUpperCase().includes(input) || area.includes(input);
            items[i].style.display = match ? "" : "none";
            if (match) anyVisible = true;
        }
        section.style.display = anyVisible ? "" : "none";
        list.style.display = anyVisible ? "" : "none";
    });
}
</script>
</body>
</html>
""")


# ---------- page sections ----------

def render_evo_line(evo: dict[str, Any], direction: str) -> str:
    method = str(evo.get("Method", ""))
    method_desc = METHOD_MAP.get(method, method)
    param_readable = item_or_param_name(evo.get("Param"))
    other = species_no_prefix(evo.get("Species"))
    if not other:
        return ""

    if direction == "from":
        line = f"      <li>Evolves from <a href='{other.lower()}.html'>{escape(other)}</a> via {escape(method_desc)}"
    else:
        line = f"      <li>Evolves into <a href='{other.lower()}.html'>{escape(other)}</a> via {escape(method_desc)}"
    if param_readable:
        line += f" <strong>{escape(param_readable)}</strong>"
    line += "</li>\n"
    return line


def render_move_table(title: str, header: str, moves: list[str]) -> str:
    html = [f"<h3 class='center'>{escape(title)}</h3>", "<table>", f"  <tr><th>{escape(header)}</th></tr>"]
    if moves:
        for move in moves:
            html.append(f"  <tr><td>{escape(move_name(move))}</td></tr>")
    else:
        html.append("  <tr><td>(none)</td></tr>")
    html.append("</table>")
    return "\n".join(html)


def render_level_moves(level_moves: list[dict[str, Any]]) -> str:
    rows: list[tuple[int, str]] = []
    for row in level_moves or []:
        try:
            level = int(row.get("Level", 0))
        except Exception:
            continue
        rows.append((level, move_name(str(row.get("Move", "MOVE_NONE")))))
    rows.sort(key=lambda x: (x[0], x[1]))

    if not rows:
        return "<p><em>Moves not found.</em></p>"

    html = ["<table>", "  <tr><th>Level</th><th>Move</th></tr>"]
    for level, move in rows:
        html.append(f"  <tr><td>{level}</td><td>{escape(move)}</td></tr>")
    html.append("</table>")
    return "\n".join(html)


def sprite_tag(species: str, sprite_root: Path | None, output_dir: Path, sprite_out: str) -> str:
    if not sprite_root:
        return "<p><em>No image available</em></p>"
    sprite_path = sprite_root / species.lower() / "male" / "front.png"
    if not sprite_path.exists():
        return "<p><em>No image available</em></p>"
    sprite_dir = output_dir / sprite_out
    sprite_dir.mkdir(parents=True, exist_ok=True)
    sprite_dst = sprite_dir / f"{species.lower()}.png"
    shutil.copy(sprite_path, sprite_dst)
    return f"<div class='sprite-frame'><img src='{sprite_out}/{species.lower()}.png' alt='{species.lower()}' class='sprite crop'/></div>"


# ---------- main generation ----------

def generate_pokemon_pages(json_path: Path, output_dir: Path, sprite_root: Path | None = None) -> None:
    data = load_species_json(json_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    species_locations = build_species_locations(data)
    sprite_out = "sprites"

    generated = 0
    for species_const, entry in data.items():
        species = species_no_prefix(species_const)
        if not species or species.isdigit():
            continue

        stats = get_base_stats(entry)
        types = get_types(entry)
        abilities = get_abilities(entry)
        learnsets = entry.get("Learnsets", {}) or {}
        evos = entry.get("Evolutions", {}) or {}

        img_tag = sprite_tag(species, sprite_root, output_dir, sprite_out)

        stats_html = "".join(render_stat_bar(stat, value) for stat, value in stats.items()) or "<p><em>Stats not found.</em></p>"
        abilities_html = " / ".join(
            f"<a href='https://bulbapedia.bulbagarden.net/wiki/{escape(ability.replace('_', ' ').title())}_(Ability)' target='_blank'>{escape(ability.replace('_', ' ').title())}</a>"
            for ability in abilities
        ) or "<p><em>Abilities not found.</em></p>"
        types_html = "".join(f"<span class='type {escape(t.lower())}'>{escape(t.title())}</span>" for t in types) or "<p><em>Typing not found.</em></p>"
        locations_html = render_species_locations_grouped(species_locations, species)

        html_path = output_dir / f"{species.lower()}.html"
        with html_path.open("w", encoding="utf-8") as f:
            f.write(f"""<!DOCTYPE html>
        <html lang='en'>
          <head>
            <meta charset='UTF-8'>
            <title>{escape(species.replace("_", " ").title())}</title>
            <link rel='stylesheet' type='text/css' href='../style.css'>
          </head>
          <body>
            <h1 class='center'>Mirror Gold Pokédex</h1>
            <h3 class='center'><a href='./index.html'>Back to Pokédex Index</a></h3>
            <h2 class='center'>{escape(species.replace("_", " ").title())}</h2>
            <div class='sprite info-line'>{img_tag}</div>
            <div class='center info-line'>
              <strong>Type:</strong>
            </div>
            <div class='center info-line'>
              {types_html}
            </div>
            <div class='center info-line'>
              <strong>Abilities:</strong>
            </div>
            <div class='center info-line'>
              {abilities_html}
            </div>
            <h3 class='center'>Base Stats</h3>
            <div class='center info-line'>
                {stats_html}
            </div>
""")

            pre_evolutions = evos.get("From", []) or []
            if pre_evolutions:
                f.write("    <h3 class='center'>Evolves From</h3>\n    <ul class='center'>\n")
                for evo in pre_evolutions:
                    f.write(render_evo_line(evo, "from"))
                f.write("    </ul>\n")

            evolutions = evos.get("To", []) or []
            if evolutions:
                f.write("    <h3 class='center'>Evolves To</h3>\n    <ul class='center'>\n")
                for evo in evolutions:
                    f.write(render_evo_line(evo, "to"))
                f.write("    </ul>\n")

            related_forms = [species_no_prefix(s) for s in (entry.get("AlternateForms", []) or [])]
            related_forms = sorted(set(x for x in related_forms if x and x != species))
            if related_forms:
                f.write("    <h3 class='center'>Other Forms</h3>\n    <ul class='center'>\n")
                for form in related_forms:
                    f.write(f"      <li><a href='{form.lower()}.html'>{escape(form.replace('_', ' ').title())}</a></li>\n")
                f.write("    </ul>\n")

            level_html = render_level_moves(learnsets.get("LevelMoves", []) or [])
            machine_html = render_move_table("Machine Moves", "Machine Move", learnsets.get("MachineMoves", []) or [])
            # tutor_html = render_move_table("Tutor Moves", "Tutor Move", learnsets.get("TutorMoves", []) or [])
            tutor_html = ""
            egg_html = render_move_table("Egg Moves", "Egg Move", learnsets.get("EggMoves", []) or [])

            f.write(f"""
                <h3 class='center'>Level-Up Moves</h3>
                {level_html}

                {machine_html}

                {tutor_html}

                {egg_html}

            <h3 class='center'>Wild Locations</h3>
            {locations_html}
            """)

            f.write("""    <h3 class='center'><a href='./index.html'>Back to Pokédex Index</a></h3>
          </body>
        </html>
        """)
        generated += 1

    generate_pokemon_area_index(data, output_dir / "index.html")
    print(f"Generated {generated} pages in '{output_dir}/'")
    print(f"Grouped Pokédex index generated at {output_dir / 'index.html'} with {len(data)} entries.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Pokémon wiki HTML from merged species JSON.")
    ap.add_argument("--json", type=Path, default=Path("species_with_learnsets.json"), help="merged per-species JSON from json_mapping.py")
    ap.add_argument("--output-dir", type=Path, default=Path("docs/pokedex"))
    ap.add_argument("--sprite-root", type=Path, default=Path("../hg-engine/data/graphics/sprites"), help="set to missing path or omit sprites if unavailable")
    args = ap.parse_args()

    sprite_root = args.sprite_root if args.sprite_root and args.sprite_root.exists() else None
    generate_pokemon_pages(args.json, args.output_dir, sprite_root=sprite_root)


if __name__ == "__main__":
    main()
