import hmac
import os
import secrets
import time
import uuid
from collections import Counter
from datetime import timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)
from supabase import create_client

load_dotenv()
URL = os.environ["SUPABASE_URL"]
LLAVE_PUBLICA = os.environ["SUPABASE_PUBLISHABLE_KEY"]
LLAVE_SECRETA = os.environ["SUPABASE_SECRET_KEY"]

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),  # duración de "Recordarme"
)
INACTIVIDAD = 30 * 60  # segundos sin actividad antes de cerrar la sesión

# Cliente del servidor: usa la llave secreta y se salta RLS. Nunca sale del backend.
db = create_client(URL, LLAVE_SECRETA)

ROL_BD = {"alumno": "alumno", "profesor": "profesor", "admin": "administrador"}
ETIQUETA = {"alumno": "Alumno", "profesor": "Profesor", "admin": "Administrativo"}
INICIO = {"alumno": "panel_alumno", "profesor": "panel_profesor", "admin": "panel_admin"}


# ======================= Seguridad y utilidades =======================
def token_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def verificar_csrf():
    if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
        abort(400)


app.jinja_env.globals["token_csrf"] = token_csrf


@app.template_filter("nota")
def nota(valor):
    if valor is None:
        return "—"
    valor = float(valor)
    return str(int(valor)) if valor == int(valor) else f"{valor:.1f}"


def uuid_valido(valor):
    try:
        return str(uuid.UUID(str(valor)))
    except ValueError:
        return None


@app.before_request
def vigilar_inactividad():
    if "uid" not in session:
        return None
    ahora = time.time()
    if not session.get("recordar") and ahora - session.get("ultima", ahora) > INACTIVIDAD:
        session.clear()
        return redirect(url_for("login"))
    session["ultima"] = ahora
    return None


def rol_requerido(rol):
    """Protege una vista: solo entra el rol indicado."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if session.get("rol") != rol:
                return redirect(url_for("login"))
            return vista(*args, **kwargs)
        return envoltura
    return decorador


def pagina(plantilla, **datos):
    return render_template(plantilla, etiqueta=ETIQUETA[session["rol"]], **datos)


# ======================= Login con Supabase Auth =======================
def buscar_usuario(tipo, identificador):
    """Busca por matrícula / ID de trabajador / usuario. Devuelve (fila de usuarios, nombre) o None."""
    if tipo == "admin":
        filas = (db.table("usuarios").select("id_usuario,correo,rol,usuario")
                 .eq("usuario", identificador).limit(1).execute().data)
        return (filas[0], filas[0]["usuario"]) if filas else None

    tabla, columna = ("alumnos", "matricula") if tipo == "alumno" else ("profesores", "num_empleado")
    perfil = (db.table(tabla).select("id_usuario,nombre_completo")
              .eq(columna, identificador).limit(1).execute().data)
    if not perfil:
        return None
    filas = (db.table("usuarios").select("id_usuario,correo,rol")
             .eq("id_usuario", perfil[0]["id_usuario"]).limit(1).execute().data)
    return (filas[0], perfil[0]["nombre_completo"]) if filas else None


def autenticar(tipo, identificador, clave):
    """Devuelve los datos de sesión o None. Cualquier fallo da el mismo resultado."""
    if tipo not in ROL_BD or not identificador or not clave or len(identificador) > 50:
        return None
    try:
        encontrado = buscar_usuario(tipo, identificador)
        if not encontrado:
            return None
        usuario, nombre = encontrado
        if usuario["rol"] != ROL_BD[tipo]:
            return None
        # Cliente nuevo por intento: una sesión nunca se mezcla con la de otra persona.
        create_client(URL, LLAVE_PUBLICA).auth.sign_in_with_password(
            {"email": usuario["correo"], "password": clave})
    except Exception as error:  # el motivo real se ve en la terminal, no en la pantalla
        app.logger.warning("Login rechazado (%s): %s", tipo, error)
        return None
    return {"uid": usuario["id_usuario"], "rol": tipo, "nombre": nombre}


@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("uid"):
        return redirect(url_for(INICIO[session["rol"]]))
    error, tipo = None, "alumno"
    if request.method == "POST":
        verificar_csrf()
        tipo = request.form.get("rol", "alumno")
        datos = autenticar(tipo, request.form.get("identificador", "").strip(),
                           request.form.get("contrasena", ""))
        if datos:
            recordar = bool(request.form.get("recordarme"))
            session.clear()
            session.update(datos, recordar=recordar, ultima=time.time())
            session.permanent = recordar
            return redirect(url_for(INICIO[datos["rol"]]))
        error = "Datos incorrectos."  # no revela si el ID existe ni de qué rol es
        if tipo not in ROL_BD:
            tipo = "alumno"
    return render_template("login.html", tipo=tipo, error=error)


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


# ======================= Consultas compartidas =======================
def todas_materias():
    filas = db.table("materias").select("id_materia,nombre,clave").execute().data
    return sorted(filas, key=lambda m: m["nombre"])


def todos_grupos():
    """Todos los grupos, con una etiqueta (G1, G2...) numerada dentro de cada materia."""
    grupos = (db.table("grupos")
              .select("id_grupo,id_materia,id_profesor,periodo,horario,cupo_maximo").execute().data)
    cuenta = {}
    for g in sorted(grupos, key=lambda g: (str(g["id_materia"]), str(g["id_grupo"]))):
        cuenta[g["id_materia"]] = cuenta.get(g["id_materia"], 0) + 1
        g["etiqueta"] = f"G{cuenta[g['id_materia']]}"
    return grupos


def ocupados():
    filas = db.table("inscripciones").select("id_grupo").eq("estatus", "activa").execute().data
    return Counter(f["id_grupo"] for f in filas if f["id_grupo"])


def nombres_profesores():
    filas = db.table("profesores").select("id_profesor,nombre_completo").execute().data
    return {f["id_profesor"]: f["nombre_completo"] for f in filas}


def calificaciones_de(ids_inscripcion):
    if not ids_inscripcion:
        return {}
    filas = (db.table("calificaciones")
             .select("id_inscripcion,parcial_1,parcial_2,parcial_3,final")
             .in_("id_inscripcion", ids_inscripcion).execute().data)
    return {f["id_inscripcion"]: f for f in filas}


def promedio(p1, p2, p3):
    """Promedio de los tres parciales (1 decimal); None si falta alguno."""
    if None in (p1, p2, p3):
        return None
    return round((p1 + p2 + p3) / 3, 1)


# ======================= Alumno =======================
def alumno_actual():
    filas = (db.table("alumnos").select("matricula,nombre_completo")
             .eq("id_usuario", session["uid"]).limit(1).execute().data)
    if not filas:
        abort(404)
    return filas[0]


@app.route("/alumno")
@rol_requerido("alumno")
def panel_alumno():
    """Interfaz 3: materias inscritas y calificaciones. Sin inscripciones, manda a inscribirse."""
    alumno = alumno_actual()
    ins = (db.table("inscripciones").select("id_inscripcion,id_materia,id_grupo")
           .eq("matricula", alumno["matricula"]).eq("estatus", "activa").execute().data)
    if not ins:
        return redirect(url_for("alumno_inscripcion"))
    materias = {m["id_materia"]: m for m in todas_materias()}
    grupos = {g["id_grupo"]: g for g in todos_grupos()}
    califs = calificaciones_de([i["id_inscripcion"] for i in ins])
    filas = []
    for i in ins:
        m, g = materias.get(i["id_materia"], {}), grupos.get(i["id_grupo"], {})
        c = califs.get(i["id_inscripcion"], {})
        filas.append(dict(materia=m.get("nombre", "—"), clave=m.get("clave", "—"),
                          grupo=g.get("etiqueta", "—"), horario=g.get("horario", "—"),
                          p1=c.get("parcial_1"), p2=c.get("parcial_2"),
                          p3=c.get("parcial_3"), final=c.get("final")))
    filas.sort(key=lambda f: f["materia"])
    return pagina("alumno_calificaciones.html", filas=filas)


@app.route("/alumno/inscripcion")
@rol_requerido("alumno")
def alumno_inscripcion():
    """Interfaces 1 y 2 juntas: elegir materia y marcar un grupo."""
    alumno = alumno_actual()
    materias = todas_materias()
    claves = {m["id_materia"]: m["clave"] for m in materias}
    profes, ocup = nombres_profesores(), ocupados()
    grupos = []
    for g in todos_grupos():
        libres = None if g["cupo_maximo"] is None else max(g["cupo_maximo"] - ocup[g["id_grupo"]], 0)
        grupos.append(dict(g, clave=claves.get(g["id_materia"], "—"), libres=libres,
                           profesor=profes.get(g["id_profesor"], "Sin profesor")))
    grupos.sort(key=lambda g: (g["clave"], g["etiqueta"]))
    tiene = bool(db.table("inscripciones").select("id_inscripcion")
                 .eq("matricula", alumno["matricula"]).eq("estatus", "activa").limit(1).execute().data)
    return pagina("alumno_inscripcion.html", materias=materias, grupos=grupos, tiene=tiene)


@app.route("/alumno/inscribir", methods=["POST"])
@rol_requerido("alumno")
def alumno_inscribir():
    verificar_csrf()
    alumno = alumno_actual()
    id_grupo = uuid_valido(request.form.get("id_grupo"))
    grupo = None
    if id_grupo:
        filas = (db.table("grupos").select("id_grupo,id_materia,id_profesor,periodo,cupo_maximo")
                 .eq("id_grupo", id_grupo).limit(1).execute().data)
        grupo = filas[0] if filas else None
    if not grupo:
        flash("Elige un grupo válido.", "error")
        return redirect(url_for("alumno_inscripcion"))
    if grupo["cupo_maximo"] is not None and ocupados()[id_grupo] >= grupo["cupo_maximo"]:
        flash("Ese grupo ya no tiene lugares.", "error")
        return redirect(url_for("alumno_inscripcion"))
    previas = (db.table("inscripciones").select("id_materia,periodo")
               .eq("matricula", alumno["matricula"]).eq("estatus", "activa").execute().data)
    if any(p["id_materia"] == grupo["id_materia"] and p["periodo"] == grupo["periodo"] for p in previas):
        flash("Ya estás inscrito en esa materia en este periodo.", "error")
        return redirect(url_for("alumno_inscripcion"))
    id_inscripcion = str(uuid.uuid4())
    db.table("inscripciones").insert({
        "id_inscripcion": id_inscripcion, "matricula": alumno["matricula"],
        "id_materia": grupo["id_materia"], "id_profesor": grupo["id_profesor"],
        "periodo": grupo["periodo"], "id_grupo": id_grupo, "estatus": "activa"}).execute()
    db.table("calificaciones").insert({
        "id_calificacion": str(uuid.uuid4()), "id_inscripcion": id_inscripcion}).execute()
    flash("Materia inscrita correctamente.", "ok")
    return redirect(url_for("panel_alumno"))


# ======================= Profesor =======================
def profesor_actual():
    filas = (db.table("profesores").select("id_profesor,nombre_completo")
             .eq("id_usuario", session["uid"]).limit(1).execute().data)
    if not filas:
        abort(404)
    return filas[0]


def grupo_del_profesor(id_grupo):
    """Devuelve el grupo solo si lo imparte el profesor de la sesión."""
    id_grupo = uuid_valido(id_grupo)
    if not id_grupo:
        return None
    id_profesor = profesor_actual()["id_profesor"]
    for g in todos_grupos():
        if g["id_grupo"] == id_grupo and g["id_profesor"] == id_profesor:
            return g
    return None


def alumnos_del_grupo(id_grupo):
    ins = (db.table("inscripciones").select("id_inscripcion,matricula")
           .eq("id_grupo", id_grupo).eq("estatus", "activa").execute().data)
    if not ins:
        return [], {}
    alumnos = db.table("alumnos").select("matricula,nombre_completo").in_(
        "matricula", [i["matricula"] for i in ins]).execute().data
    nombres = {a["matricula"]: a["nombre_completo"] for a in alumnos}
    filas = [dict(i, nombre=nombres.get(i["matricula"], "—")) for i in ins]
    filas.sort(key=lambda f: f["nombre"])
    return filas, calificaciones_de([i["id_inscripcion"] for i in ins])


@app.route("/profesor")
@rol_requerido("profesor")
def panel_profesor():
    """Interfaces 4 y 5 juntas: elegir materia y marcar uno de sus grupos."""
    id_profesor = profesor_actual()["id_profesor"]
    propios = [g for g in todos_grupos() if g["id_profesor"] == id_profesor]
    materias = {m["id_materia"]: m for m in todas_materias()}
    ocup = ocupados()
    filas = [dict(g, clave=materias.get(g["id_materia"], {}).get("clave", "—"),
                  inscritos=ocup[g["id_grupo"]]) for g in propios]
    filas.sort(key=lambda g: (g["clave"], g["etiqueta"]))
    ids = {g["id_materia"] for g in propios if g["id_materia"] in materias}
    lista = sorted((materias[i] for i in ids), key=lambda m: m["nombre"])
    return pagina("profesor_materia.html", materias=lista, grupos=filas)


@app.route("/profesor/alumnos")
@rol_requerido("profesor")
def profesor_alumnos():
    """Interfaz 6: alumnos del grupo con sus parciales."""
    grupo = grupo_del_profesor(request.args.get("id_grupo"))
    if not grupo:
        flash("Elige uno de tus grupos.", "error")
        return redirect(url_for("panel_profesor"))
    filas, califs = alumnos_del_grupo(grupo["id_grupo"])
    for f in filas:
        f["c"] = califs.get(f["id_inscripcion"], {})
    materia = next((m["nombre"] for m in todas_materias() if m["id_materia"] == grupo["id_materia"]), "—")
    return pagina("profesor_alumnos.html", grupo=grupo, materia=materia, filas=filas)


@app.route("/profesor/guardar", methods=["POST"])
@rol_requerido("profesor")
def profesor_guardar():
    verificar_csrf()
    grupo = grupo_del_profesor(request.form.get("id_grupo"))
    if not grupo:
        abort(403)
    filas, califs = alumnos_del_grupo(grupo["id_grupo"])
    cambios = {}
    for f in filas:
        valores = []
        for n in (1, 2, 3):
            texto = request.form.get(f"p{n}_{f['id_inscripcion']}", "").strip()
            try:
                v = float(texto) if texto else None
            except ValueError:
                v = -1
            if v is not None and not 0 <= v <= 100:
                flash("Las calificaciones deben estar entre 0 y 100.", "error")
                return redirect(url_for("profesor_alumnos", id_grupo=grupo["id_grupo"]))
            valores.append(v)
        cambios[f["id_inscripcion"]] = dict(parcial_1=valores[0], parcial_2=valores[1],
                                            parcial_3=valores[2], final=promedio(*valores))
    for id_inscripcion, datos in cambios.items():
        if id_inscripcion in califs:
            db.table("calificaciones").update(datos).eq("id_inscripcion", id_inscripcion).execute()
        else:
            db.table("calificaciones").insert(
                dict(datos, id_calificacion=str(uuid.uuid4()), id_inscripcion=id_inscripcion)).execute()
    flash("Calificaciones guardadas.", "ok")
    return redirect(url_for("profesor_alumnos", id_grupo=grupo["id_grupo"]))


# ======================= Administrativo =======================
@app.route("/admin")
@rol_requerido("admin")
def panel_admin():
    """Interfaz 7: menú."""
    return pagina("admin_menu.html")


@app.route("/admin/profesores")
@rol_requerido("admin")
def admin_profesores():
    """Interfaz 8: profesores y la materia que imparten."""
    profes = db.table("profesores").select("id_profesor,nombre_completo,num_empleado").execute().data
    materias = {m["id_materia"]: m["nombre"] for m in todas_materias()}
    grupos = todos_grupos()
    filas = []
    for p in sorted(profes, key=lambda p: p["nombre_completo"]):
        propios = [g for g in grupos if g["id_profesor"] == p["id_profesor"]]
        if not propios:
            filas.append(dict(p, materia="—", id_grupo=None))
        for g in propios:
            filas.append(dict(p, materia=f"{materias.get(g['id_materia'], '—')} ({g['etiqueta']})",
                              id_grupo=g["id_grupo"]))
    return pagina("admin_profesores.html", filas=filas)


@app.route("/admin/profesores/baja", methods=["POST"])
@rol_requerido("admin")
def admin_profesores_baja():
    verificar_csrf()
    ids = [i for i in (uuid_valido(v) for v in request.form.getlist("baja")) if i]
    if not ids:
        flash("No marcaste ninguna baja.", "error")
        return redirect(url_for("admin_profesores"))
    try:
        db.table("grupos").update({"id_profesor": None}).in_("id_grupo", ids).execute()
        flash("Bajas confirmadas: los grupos quedaron sin profesor.", "ok")
    except Exception as error:
        app.logger.warning("Baja de profesor falló: %s", error)
        flash("No se pudo aplicar la baja (revisa que grupos.id_profesor acepte valores vacíos).", "error")
    return redirect(url_for("admin_profesores"))


@app.route("/admin/materias")
@rol_requerido("admin")
def admin_materias():
    """Interfaces 9 y 10 juntas: elegir materia y grupo."""
    profes = nombres_profesores()
    grupos = [dict(g, profesor=profes.get(g["id_profesor"], "Sin profesor")) for g in todos_grupos()]
    grupos.sort(key=lambda g: (str(g["id_materia"]), g["etiqueta"]))
    return pagina("admin_materias.html", materias=todas_materias(), grupos=grupos)


@app.route("/admin/alumnos")
@rol_requerido("admin")
def admin_alumnos():
    """Interfaz 11: alumnos del grupo, con baja."""
    id_grupo = uuid_valido(request.args.get("id_grupo"))
    grupo = next((g for g in todos_grupos() if g["id_grupo"] == id_grupo), None)
    if not grupo:
        flash("Elige una materia y un grupo.", "error")
        return redirect(url_for("admin_materias"))
    filas, califs = alumnos_del_grupo(id_grupo)
    for f in filas:
        f["c"] = califs.get(f["id_inscripcion"], {})
    materia = next((m["nombre"] for m in todas_materias() if m["id_materia"] == grupo["id_materia"]), "—")
    return pagina("admin_alumnos.html", grupo=grupo, materia=materia, filas=filas)


@app.route("/admin/alumnos/baja", methods=["POST"])
@rol_requerido("admin")
def admin_alumnos_baja():
    verificar_csrf()
    id_grupo = uuid_valido(request.form.get("id_grupo"))
    if not id_grupo:
        abort(400)
    filas, _ = alumnos_del_grupo(id_grupo)
    validos = {f["id_inscripcion"] for f in filas}
    marcados = [i for i in (uuid_valido(v) for v in request.form.getlist("baja")) if i in validos]
    if marcados:
        db.table("inscripciones").update({"estatus": "baja"}).in_("id_inscripcion", marcados).execute()
        flash("Bajas confirmadas.", "ok")
    else:
        flash("No marcaste ninguna baja.", "error")
    return redirect(url_for("admin_alumnos", id_grupo=id_grupo))


if __name__ == "__main__":
    app.run(debug=True)  # debug solo en desarrollo
