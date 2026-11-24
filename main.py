# ============================================================
#   «Мировой Атлас» — лэндинг (одностраничный сайт) на FastAPI
#   Школьный проект.
#
#   Что умеет:
#     * три уровня доступа: гость (ничего не может),
#       читатель (только просмотр) и админ (может всё);
#     * пользователи хранятся в users.csv (логин, хэш пароля,
#       соль, роль, путь к аватарке, дата регистрации);
#     * весь остальной контент (текст главной и справочник
#       стран) хранится в data.csv;
#     * все действия пользователей пишутся в журнал logs.txt;
#     * сессия живёт 5 минут бездействия, потом нужен вход.
#
#   Запуск:   python main.py     →  http://127.0.0.1:8000
#   Тестовые аккаунты: admin / admin123, reader / reader123
# ============================================================

import csv
import hashlib
import json
import uvicorn
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

# ---------- пути и главные настройки ----------

BASE_DIR = Path(__file__).parent
USERS_FILE = BASE_DIR / "users.csv"      # пользователи сайта
DATA_FILE = BASE_DIR / "data.csv"        # контент сайта и справочник стран
LOG_FILE = BASE_DIR / "logs.txt"         # журнал действий пользователей
AVATAR_DIR = BASE_DIR / "static" / "avatars"

SESSION_MINUTES = 5                      # таймаут сессии — 5 минут
LOGIN_RE = re.compile(r"^[a-zA-Z0-9_-]{3,20}$")   # допустимые логины

# цвета для автоматических аватарок (голубой, зелёный и друзья)
AVATAR_COLORS = ["#4da8e0", "#5fbf74", "#f2b134", "#8e7cc3", "#ef8a68", "#55b8c9"]

# тексты всплывающих сообщений (передаются через ?m=код)
FLASH = {
    "reg_ok": ("ok", "Регистрация прошла успешно! Вы вошли как читатель."),
    "wrong": ("err", "Неверный логин или пароль."),
    "bye": ("ok", "Вы вышли из системы."),
    "session": ("err", "Сессия истекла: прошло больше 5 минут без действий. Войдите снова."),
    "need_login": ("err", "Сначала войдите в систему."),
    "saved": ("ok", "Содержимое главной страницы сохранено."),
    "country_saved": ("ok", "Карточка страны обновлена."),
    "country_bad": ("err", "Не удалось сохранить карточку: проверьте числа."),
    "avatar_ok": ("ok", "Аватарка загружена."),
    "avatar_bad": ("err", "Аватарка не загружена: нужен PNG/JPG/GIF размером до 2 МБ."),
    "pass_ok": ("ok", "Пароль изменён."),
    "pass_wrong": ("err", "Старый пароль неверен."),
    "pass_match": ("err", "Новые пароли не совпадают или короче 5 символов."),
    "role_ok": ("ok", "Роль пользователя изменена."),
    "role_self": ("err", "Нельзя менять роль самому себе."),
    "del_ok": ("ok", "Пользователь удалён."),
    "del_self": ("err", "Нельзя удалить свой собственный аккаунт."),
    "user_exists": ("err", "Такой логин уже занят."),
    "reg_match": ("err", "Пароли не совпадают или короче 5 символов, логин — 3-20 латинских букв и цифр."),
    "login_bad": ("err", "Логин: 3-20 латинских букв, цифр, «_» или «-». Пароль: минимум 5 символов."),
}

# содержимое главной страницы «из коробки» (админ потом меняет через /edit)
DEFAULT_PAGE = {
    "hero_title": "Интерактивная карта современного мира",
    "hero_text": ("Небольшой сайт-лэндинг о странах мира: нажмите на любое государство "
                  "на карте — и откроется карточка с флагом, гербом, населением, "
                  "площадью и короткой справкой. Всего в справочнике 195 государств "
                  "(193 члена ООН, а также Ватикан и Палестина)."),
}
DEFAULT_BLOCKS = [
    {"key": "b1", "title": "📚 О проекте",
     "text": ("Это учебный сайт, сделанный на FastAPI с шаблонами Jinja2 и картой Plotly. "
              "Пользователи хранятся в файле users.csv, содержимое сайта — в data.csv, "
              "а все действия записываются в журнал logs.txt. Данные о странах собраны "
              "из открытых источников: Викиданные и набор mledoze/countries.")},
    {"key": "b2", "title": "👥 Три уровня доступа",
     "text": ("Гость не может ничего — сначала нужно войти или зарегистрироваться. "
              "Читатель просматривает главную страницу, карту стран и свой профиль. "
              "Админ может всё: менять текст главной, добавлять и удалять блоки, "
              "редактировать карточки стран, управлять пользователями и аватарками.")},
    {"key": "b3", "title": "🔐 Как устроена безопасность",
     "text": ("Пароли не хранятся в открытом виде — в users.csv записан только "
              "sha256-хэш с случайной солью. Сессия пользователя живёт 5 минут "
              "после последнего действия, потом требуется вход. Каждый переход "
              "и каждое действие попадает в logs.txt с датой и временем.")},
    {"key": "b4", "title": "🗺️ Карта и карточки",
     "text": ("Карта построена библиотекой Plotly прямо из data.csv, поэтому работает "
              "даже без интернета (движок лежит в static/plotly.min.js). Кликните "
              "на страну — всплывёт карточка с флагом и гербом. Картинки флагов "
              "и гербов подгружаются с Wikimedia Commons.")},
]

app = FastAPI(title="Мировой Атлас")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# ============================================================
#   Работа с CSV-файлами
# ============================================================

def read_users():
    """Читает users.csv в список словарей."""
    if not USERS_FILE.exists():
        return []
    with open(USERS_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_users(rows):
    """Сохраняет список пользователей обратно в users.csv."""
    fields = ["login", "password_hash", "salt", "role", "avatar", "created"]
    with open(USERS_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def find_user(login):
    """Ищет пользователя по логину."""
    for u in read_users():
        if u["login"] == login:
            return u
    return None


def read_data():
    """Читает data.csv: текст главной, блоки и справочник стран."""
    data = {"page": {}, "blocks": [], "countries": {}}
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) != 3 or row[0] == "type":
                    continue
                kind, key, value = row
                if kind == "page":
                    data["page"][key] = value
                elif kind == "block":
                    try:
                        data["blocks"].append({"key": key, **json.loads(value)})
                    except json.JSONDecodeError:
                        continue
                elif kind == "country":
                    try:
                        data["countries"][key] = json.loads(value)
                    except json.JSONDecodeError:
                        continue
    # если файлов ещё нет — создаём содержимое по умолчанию
    changed = False
    for k, v in DEFAULT_PAGE.items():
        if k not in data["page"]:
            data["page"][k] = v
            changed = True
    if not data["blocks"]:
        data["blocks"] = [dict(b) for b in DEFAULT_BLOCKS]
        changed = True
    if changed:
        write_data(data)
    return data


def write_data(data):
    """Сохраняет контент сайта в data.csv (страница → блоки → страны)."""
    with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["type", "key", "value"])
        for k, v in data["page"].items():
            w.writerow(["page", k, v])
        for b in data["blocks"]:
            w.writerow(["block", b["key"],
                        json.dumps({"title": b["title"], "text": b["text"]},
                                   ensure_ascii=False)])
        for iso in sorted(data["countries"]):
            w.writerow(["country", iso,
                        json.dumps(data["countries"][iso], ensure_ascii=False)])


def log(login, action):
    """Пишет строчку в журнал logs.txt: кто, когда и что сделал."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {login}: {action}\n")


def make_avatar(login):
    """Делает простую SVG-аватарку: цветной квадрат с первой буквой логина."""
    letter = login[0].upper()
    color = AVATAR_COLORS[sum(ord(c) for c in login) % len(AVATAR_COLORS)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="150" height="150">'
           f'<rect width="150" height="150" rx="30" fill="{color}"/>'
           f'<text x="75" y="88" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" '
           f'font-size="64" font-weight="bold" fill="#ffffff">{letter}</text></svg>')
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    (AVATAR_DIR / f"{login}.svg").write_text(svg, encoding="utf-8")
    return f"/static/avatars/{login}.svg"


def hash_password(password, salt):
    """Хэш пароля: sha256(соль + пароль). Сам пароль нигде не хранится."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def create_default_files():
    """При первом запуске создаёт users.csv с двумя аккаунтами-примерами."""
    if not USERS_FILE.exists():
        admin_salt = secrets.token_hex(8)
        reader_salt = secrets.token_hex(8)
        write_users([
            {"login": "admin", "password_hash": hash_password("admin123", admin_salt),
             "salt": admin_salt, "role": "admin", "avatar": make_avatar("admin"),
             "created": datetime.now().strftime("%Y-%m-%d")},
            {"login": "reader", "password_hash": hash_password("reader123", reader_salt),
             "salt": reader_salt, "role": "reader", "avatar": make_avatar("reader"),
             "created": datetime.now().strftime("%Y-%m-%d")},
        ])
        log("admin", "создан файл users.csv с тестовыми аккаунтами admin и reader")


# ============================================================
#   Сессии (в памяти сервера, таймаут 5 минут)
# ============================================================

# sid -> {"login": ..., "role": ..., "last": время последнего действия}
SESSIONS = {}


def create_session(login, role):
    sid = secrets.token_hex(16)
    SESSIONS[sid] = {"login": login, "role": role, "last": time.time()}
    return sid


def get_user(request):
    """Возвращает текущего пользователя или None.
    Заодно проверяет таймаут: 5 минут бездействия — сессия закрывается."""
    sid = request.cookies.get("sid")
    sess = SESSIONS.get(sid)
    if sid is None or sess is None:
        return None
    if time.time() - sess["last"] > SESSION_MINUTES * 60:
        SESSIONS.pop(sid)
        log(sess["login"], "сессия истекла (5 минут бездействия)")
        request.state.session_expired = True   # чтобы показать нужное сообщение
        return None
    # пользователь мог быть удалён админом — тогда и сессия недействительна
    user = find_user(sess["login"])
    if user is None:
        SESSIONS.pop(sid)
        return None
    sess["last"] = time.time()          # продлеваем сессию
    return user


def flash_from_request(request):
    """Достаёт текст всплывающего сообщения из ?m=код."""
    code = request.query_params.get("m")
    if code in FLASH:
        kind, text = FLASH[code]
        return {"kind": kind, "text": text}
    return None


def need_login_response(request):
    """Редирект на страницу входа (с объяснением, если сессия истекла)."""
    code = "session" if getattr(request.state, "session_expired", False) else "need_login"
    return RedirectResponse(f"/login?m={code}", 303)


def render(request, template, context, status=200):
    """Рисует страницу с общими переменными (пользователь, сообщение)."""
    context.setdefault("user", get_user(request))
    context.setdefault("flash", flash_from_request(request))
    return templates.TemplateResponse(request, template, context, status_code=status)


def page_forbidden(request):
    return render(request, "403.html", {}, status=403)


# ============================================================
#   Карта мира (Plotly, строится из data.csv)
# ============================================================

def build_map(countries):
    """Собирает HTML-код choropleth-карты мира из справочника стран."""
    iso_codes = sorted(countries.keys())
    names = [countries[i]["name"] for i in iso_codes]
    fig = go.Figure(go.Choropleth(
        locations=iso_codes,
        z=list(range(1, len(iso_codes) + 1)),
        text=names,
        hovertemplate="<b>%{text}</b> (%{location})<br>"
                      "<i>нажмите, чтобы открыть карточку</i><extra></extra>",
        colorscale=[[0.0, "#8ed4f5"], [0.55, "#4da8e0"], [1.0, "#5fbf74"]],
        showscale=False,
        marker_line_color="#ffffff",
        marker_line_width=0.6,
    ))
    fig.update_geos(
        projection_type="natural earth",
        showcoastlines=True, coastlinecolor="#a8c4d8",
        showland=True, landcolor="#eef7ee",
        showocean=True, oceancolor="#dcf0fb",
        showframe=False,
    )
    fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0},
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id="world-map")


create_default_files()          # создаём файлы при первом запуске
MAP_HTML = build_map(read_data()["countries"])


# ============================================================
#   Журнал переходов: каждое открытие страницы попадает в logs.txt
# ============================================================

@app.middleware("http")
async def log_visits(request: Request, call_next):
    response = await call_next(request)
    if request.method == "GET" and not request.url.path.startswith("/static"):
        sid = request.cookies.get("sid")
        login = SESSIONS[sid]["login"] if sid in SESSIONS else "гость"
        log(login, f"переход на страницу {request.url.path}")
    return response


# ============================================================
#   Страницы
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    data = read_data()
    # < заменяем на \u003c, чтобы JSON нельзя было сломать тегом </script>
    countries_json = json.dumps(data["countries"], ensure_ascii=False).replace("<", "\\u003c")
    return render(request, "index.html", {
        "page": data["page"], "blocks": data["blocks"],
        "map_html": MAP_HTML, "countries_json": countries_json,
        "country_count": len(data["countries"]),
    })


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_user(request) is not None:
        return RedirectResponse("/", 303)
    return render(request, "login.html", {})


@app.post("/login")
async def login_post(request: Request, login: str = Form(...),
                     password: str = Form(...)):
    user = find_user(login.strip())
    if user is None or hash_password(password, user["salt"]) != user["password_hash"]:
        log(login.strip() or "гость", "неудачная попытка входа")
        return RedirectResponse("/login?m=wrong", 303)
    sid = create_session(user["login"], user["role"])
    log(user["login"], f"вход в систему (роль: {user['role']})")
    response = RedirectResponse("/", 303)
    response.set_cookie("sid", sid, max_age=SESSION_MINUTES * 60,
                        httponly=True, samesite="lax")
    return response


@app.post("/register")
async def register_post(request: Request, login: str = Form(...),
                        password: str = Form(...), password2: str = Form(...)):
    login = login.strip()
    if (not LOGIN_RE.match(login) or len(password) < 5
            or password != password2):
        return RedirectResponse("/login?m=reg_match", 303)
    if find_user(login) is not None:
        return RedirectResponse("/login?m=user_exists", 303)
    salt = secrets.token_hex(8)
    new_user = {"login": login, "password_hash": hash_password(password, salt),
                "salt": salt, "role": "reader", "avatar": make_avatar(login),
                "created": datetime.now().strftime("%Y-%m-%d")}
    rows = read_users()
    rows.append(new_user)
    write_users(rows)
    log(login, "регистрация нового пользователя (роль: читатель)")
    # сразу же входим, чтобы было удобнее
    sid = create_session(login, "reader")
    log(login, "вход в систему (роль: reader)")
    response = RedirectResponse("/?m=reg_ok", 303)
    response.set_cookie("sid", sid, max_age=SESSION_MINUTES * 60,
                        httponly=True, samesite="lax")
    return response


@app.get("/logout")
async def logout(request: Request):
    user = get_user(request)
    sid = request.cookies.get("sid")
    if sid in SESSIONS:
        SESSIONS.pop(sid)
    if user:
        log(user["login"], "выход из системы")
    response = RedirectResponse("/login?m=bye", 303)
    response.delete_cookie("sid")
    return response


@app.get("/edit", response_class=HTMLResponse)
async def edit_page(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка открыть страницу редактора (нет прав)")
        return page_forbidden(request)
    data = read_data()
    return render(request, "edit.html", {"page": data["page"], "blocks": data["blocks"]})


@app.post("/edit")
async def edit_post(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка сохранить главную страницу (нет прав)")
        return page_forbidden(request)

    form = await request.form()
    data = read_data()
    data["page"]["hero_title"] = form.get("hero_title", "").strip()
    data["page"]["hero_text"] = form.get("hero_text", "").strip()

    # обновляем существующие блоки и убираем отмеченные на удаление
    kept = []
    for b in data["blocks"]:
        title = form.get(f"title_{b['key']}", "").strip()
        text = form.get(f"text_{b['key']}", "").strip()
        if form.get(f"del_{b['key']}"):
            log(user["login"], f"удалил блок «{b['title']}»")
            continue
        if title and text:
            kept.append({"key": b["key"], "title": title, "text": text})
    # добавляем новый блок, если админ заполнил оба поля
    new_title = form.get("new_title", "").strip()
    new_text = form.get("new_text", "").strip()
    if new_title and new_text:
        used = {b["key"] for b in kept}
        n = 1
        while f"b{n}" in used:
            n += 1
        kept.append({"key": f"b{n}", "title": new_title, "text": new_text})
        log(user["login"], f"добавил блок «{new_title}»")
    data["blocks"] = kept

    write_data(data)
    log(user["login"], "обновил содержимое главной страницы")
    return RedirectResponse("/?m=saved", 303)


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    # сколько минут осталось до автозавершения сессии
    sess = SESSIONS.get(request.cookies.get("sid"))
    left = 0
    if sess:
        left = max(0, SESSION_MINUTES - int((time.time() - sess["last"]) // 60))
    return render(request, "profile.html", {"minutes_left": left})


@app.post("/profile/avatar")
async def avatar_post(request: Request, avatar: UploadFile = File(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка сменить аватарку (нет прав)")
        return page_forbidden(request)

    ext = Path(avatar.filename or "").suffix.lower()
    content = await avatar.read()
    if ext not in (".png", ".jpg", ".jpeg", ".gif") or not content or len(content) > 2 * 1024 * 1024:
        return RedirectResponse("/profile?m=avatar_bad", 303)

    path = AVATAR_DIR / f"{user['login']}{ext}"
    path.write_bytes(content)
    # если раньше была другая аватарка — убираем её, чтобы не плодить файлы
    old = AVATAR_DIR / Path(user["avatar"]).name
    if old != path and old.exists():
        old.unlink()

    rows = read_users()
    for r in rows:
        if r["login"] == user["login"]:
            r["avatar"] = f"/static/avatars/{path.name}"
    write_users(rows)
    log(user["login"], f"сменил аватарку ({path.name})")
    return RedirectResponse("/profile?m=avatar_ok", 303)


@app.post("/profile/password")
async def password_post(request: Request, old_password: str = Form(...),
                        new_password: str = Form(...),
                        new_password2: str = Form(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка сменить пароль (нет прав)")
        return page_forbidden(request)

    if (hash_password(old_password, user["salt"]) != user["password_hash"]
            or len(new_password) < 5 or new_password != new_password2):
        return RedirectResponse("/profile?m=pass_wrong", 303)

    salt = secrets.token_hex(8)
    rows = read_users()
    for r in rows:
        if r["login"] == user["login"]:
            r["salt"] = salt
            r["password_hash"] = hash_password(new_password, salt)
    write_users(rows)
    log(user["login"], "изменил свой пароль")
    return RedirectResponse("/profile?m=pass_ok", 303)


@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка открыть страницу пользователей (нет прав)")
        return page_forbidden(request)
    return render(request, "users.html", {"users": read_users()})


@app.post("/users/role")
async def role_post(request: Request, login: str = Form(...), role: str = Form(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка изменить роль пользователя (нет прав)")
        return page_forbidden(request)
    if login == user["login"] or role not in ("admin", "reader"):
        return RedirectResponse("/users?m=role_self", 303)

    rows = read_users()
    for r in rows:
        if r["login"] == login:
            r["role"] = role
    write_users(rows)
    # роль в живых сессиях тоже меняется, чтобы сразу подействовала
    for sess in SESSIONS.values():
        if sess["login"] == login:
            sess["role"] = role
    log(user["login"], f"изменил роль пользователя {login} на {role}")
    return RedirectResponse("/users?m=role_ok", 303)


@app.post("/users/delete")
async def delete_post(request: Request, login: str = Form(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка удалить пользователя (нет прав)")
        return page_forbidden(request)
    if login == user["login"]:
        return RedirectResponse("/users?m=del_self", 303)

    rows = [r for r in read_users() if r["login"] != login]
    write_users(rows)
    for sid in [s for s, v in SESSIONS.items() if v["login"] == login]:
        SESSIONS.pop(sid)                      # закрываем сессию удалённого
    log(user["login"], f"удалил пользователя {login}")
    return RedirectResponse("/users?m=del_ok", 303)


@app.post("/country")
async def country_post(request: Request, iso: str = Form(...),
                       info: str = Form(...), population: str = Form(...),
                       area: str = Form(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], f"попытка изменить карточку страны {iso} (нет прав)")
        return page_forbidden(request)

    data = read_data()
    country = data["countries"].get(iso.upper())
    if country is None:
        return RedirectResponse("/", 303)
    try:
        country["population"] = int(float(population.replace(" ", "").replace(",", ".")))
        country["area"] = round(float(area.replace(" ", "").replace(",", ".")), 2)
    except ValueError:
        return RedirectResponse("/?m=country_bad", 303)
    country["info"] = info.strip()

    write_data(data)
    global MAP_HTML
    MAP_HTML = build_map(data["countries"])   # карта строится заново из data.csv
    log(user["login"], f"обновил карточку страны {country['name']} ({iso.upper()})")
    return RedirectResponse("/?m=country_saved#map", 303)


# ---------- собственные страницы ошибок ----------

@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        log("гость", f"переход на несуществующую страницу {request.url.path}")
        return render(request, "404.html", {"path": request.url.path}, status=404)
    if exc.status_code == 405:
        return render(request, "404.html", {"path": request.url.path}, status=405)
    return render(request, "403.html", {}, status=exc.status_code)


