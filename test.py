import gettext
import json
import os
import pycountry
import plotly.graph_objects as go

JSON_FILE = "countries_encyclopedia.json"
HTML_FILE = "world_atlas_7params.html"
TEMPLATE_FILE = "template.html"

def build_database():
    saved_db = {}
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r", encoding="utf-8") as f:
            saved_db = json.load(f)

    # Локальный перевод названий стран на русский из установленного pycountry
    ru_trans = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["ru"])
    _ = ru_trans.gettext

    countries_db = {}
    iso_codes = []
    names_ru = []
    values = []

    for idx, c in enumerate(pycountry.countries, start=1):
        iso = c.alpha_3
        name = _(c.name)

        iso_codes.append(iso)
        names_ru.append(name)
        values.append(idx)

        if iso in saved_db:
            countries_db[iso] = saved_db[iso]
            continue

        official = _(getattr(c, "official_name", c.name))

        countries_db[iso] = {
            "name": name,
            "p1_geo": f"Официальное название: {official}. Часть света, регион, выход к морям/океанам, соседи и площадь: [заполните]",
            "p2_nature": "Климат, рельеф, запасы полезных ископаемых, водные и лесные ресурсы: [заполните]",
            "p3_demo": "Численность населения, плотность, естественный прирост, урбанизация, национальный и религиозный состав: [заполните]",
            "p4_gov": "Форма правления (республика/монархия), территориальное устройство (унитарное/федерация), политический режим: [заполните]",
            "p5_econ": "Уровень развития (развитая/развивающаяся), объем ВВП, структура хозяйства и ведущие отрасли: [заполните]",
            "p6_intl": "Участие в организациях (ООН, ЕС, БРИКС и др.), главные статьи экспорта и импорта: [заполните]",
            "p7_cult": "Ключевые исторические вехи, государственные языки, главные достопримечательности и менталитет: [заполните]"
        }

    return iso_codes, names_ru, values, countries_db

def generate_html():
    if not os.path.exists(TEMPLATE_FILE):
        print(f"Ошибка: не найден файл {TEMPLATE_FILE} в текущей папке!")
        return

    iso_codes, names_ru, values, countries_db = build_database()

    fig = go.Figure(data=go.Choropleth(
        locations=iso_codes,
        z=values,
        text=names_ru,
        hovertemplate="<b>%{text}</b> (%{location})<br><i>Кликните, чтобы открыть и редактировать досье</i><extra></extra>",
        colorscale="Teal",
        showscale=False,
        marker_line_color="#ffffff",
        marker_line_width=0.5
    ))

    fig.update_geos(
        projection_type="natural earth",
        showcoastlines=True, coastlinecolor="#888888",
        showland=True, landcolor="#f4f4f4",
        showocean=True, oceancolor="#e6f2ff",
        showframe=False
    )

    fig.update_layout(
        title_text="Интерактивный атлас мира (Кликните на страну для просмотра и редактирования)",
        margin={"r": 0, "t": 40, "l": 0, "b": 0}
    )

    # include_plotlyjs=True вшивает движок внутрь HTML, чтобы карта работала даже без интернета
    plot_div = fig.to_html(full_html=False, include_plotlyjs=True, div_id="world-map")
    db_json = json.dumps(countries_db, ensure_ascii=False)

    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template = f.read()

    final_html = (
        template
        .replace("__PLOT_DIV__", plot_div)
        .replace("__DB_JSON__", db_json)
        .replace("__JSON_FILE__", JSON_FILE)
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(final_html)

    print(f"Готово! Создан полностью автономный файл {HTML_FILE} ({len(iso_codes)} стран).")

if __name__ == "__main__":
    generate_html()
 