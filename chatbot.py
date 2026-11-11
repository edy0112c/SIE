"""Asistente de preguntas frecuentes del SIE (sin IA).

Se activa en app.py con dos líneas, después de crear `app`:
    from chatbot import chatbot_bp
    app.register_blueprint(chatbot_bp)

Para agregar o corregir respuestas, edita la lista FAQ de más abajo.
"""
import hmac
import re
import time
import unicodedata
from collections import defaultdict, deque
from difflib import SequenceMatcher

from flask import Blueprint, jsonify, request, session

chatbot_bp = Blueprint("chatbot", __name__, url_prefix="/chatbot")

LIMITE_MENSAJES = 30   # mensajes por usuario...
VENTANA = 300          # ...cada 5 minutos
UMBRAL = 2             # puntos mínimos para considerar que encontró respuesta

A, P, M = ("alumno",), ("profesor",), ("admin",)
TODOS = A + P + M

SALUDO = "Hola, soy el asistente del SIE. Puedo resolver dudas frecuentes sobre cómo usar el sistema. ¿Qué necesitas?"
NO_ENTENDI = ("No encontré una respuesta a eso. Prueba escribiéndolo de otra forma o elige una pregunta sugerida. "
              "Si necesitas ayuda de una persona, acude a control escolar.")


def e(roles, pregunta, claves, respuesta, sug=False):
    """Una entrada: roles a los que aplica, pregunta, palabras clave, respuesta y si se sugiere al inicio."""
    return {"roles": roles, "p": pregunta, "k": claves.split(), "r": respuesta, "s": sug}


FAQ = [
    # ---------- Alumno ----------
    e(A, "¿Cómo me inscribo a una materia?", "inscribir inscribo inscripcion inscribirme registrarme anotarme alta",
      "Entra a «Inscripción de materias». Elige la materia en la lista, marca el grupo que quieres en la tabla y presiona «Inscribir materia». "
      "Si ya tienes materias, usa el botón «Inscribir otra materia» en tu pantalla de calificaciones.", True),
    e(A, "¿Por qué no puedo inscribirme en un grupo?", "error rechaza lleno lugares cupo desactivada bloqueada repetida",
      "Puede ser por tres razones: el grupo ya no tiene lugares (su casilla aparece desactivada), ya estás inscrito en esa materia en el mismo periodo, "
      "o no marcaste ningún grupo. Prueba con otro grupo de la misma materia."),
    e(A, "¿Dónde veo mis calificaciones?", "calificaciones calificacion notas parciales ver consultar boleta resultados",
      "En «Mis materias y calificaciones», la pantalla que ves al iniciar sesión. Ahí aparecen el parcial 1, 2, 3 y la final de cada materia.", True),
    e(A, "¿Por qué mi calificación aparece con un guion (—)?", "guion raya vacia vacio falta aparece captura pendiente",
      "El guion (—) significa que tu profesor todavía no captura esa calificación. Aparecerá en cuanto la guarde."),
    e(A, "¿Cómo se calcula la calificación final?", "final promedio calcula calculo sacar resulta",
      "Es el promedio de los tres parciales, con un decimal. Se calcula sola cuando tu profesor ha capturado los tres. Mientras falte uno, verás un guion.", True),
    e(A, "¿Puedo darme de baja de una materia?", "baja bajar cancelar eliminar quitar dar materia",
      "Las bajas las aplica el área administrativa. Solicítala en control escolar. Una vez aplicada, la materia deja de aparecer en tu pantalla."),
    e(A, "¿Cuántos lugares quedan en un grupo?", "lugares libres cupo maximo disponibles espacio quedan",
      "En la tabla de inscripción, la columna «Cupo máximo» muestra la capacidad del grupo y «Lugares libres» cuántos quedan."),
    e(A, "¿Cómo sé quién es mi profesor y mi horario?", "profesor horario hora maestro docente salon",
      "En la tabla de inscripción aparecen el horario y el profesor de cada grupo. En tu pantalla de calificaciones puedes ver el grupo y la hora de tus materias."),
    # ---------- Profesor ----------
    e(P, "¿Cómo capturo calificaciones?", "capturar captura capturo calificaciones calificacion registrar poner parciales subir guardar",
      "Entra a «Mis grupos», elige la materia, marca el grupo y presiona «Siguiente». En la tabla escribe los parciales (0 a 100) y presiona «Guardar calificaciones».", True),
    e(P, "¿Cómo se calcula la calificación final?", "final promedio calcula calculo sacar resulta automatica",
      "La final se calcula sola al guardar, como el promedio de los tres parciales (con un decimal). Solo aparece cuando los tres están capturados.", True),
    e(P, "¿Puedo corregir una calificación ya capturada?", "corregir modificar cambiar editar error equivocado bloqueado capturada",
      "Los parciales se guardan al presionar «Guardar calificaciones». Si necesitas corregir uno ya capturado y el campo aparece bloqueado, pide el cambio al área administrativa.", True),
    e(P, "¿Qué calificaciones puedo escribir?", "rango minimo maximo decimales valores permitido cero cien",
      "Valores de 0 a 100; se permiten decimales. Si un parcial todavía no corresponde, déjalo vacío y captúralo después."),
    e(P, "¿Por qué no veo un grupo?", "grupo grupos falta aparece asignado asignacion materia",
      "En «Mis grupos» solo aparecen los grupos que tienes asignados. Si falta alguno, pide al área administrativa que te lo asigne."),
    e(P, "¿Por qué no aparecen alumnos en mi grupo?", "alumnos lista inscritos aparecen faltan baja grupo vacio",
      "Solo se muestran los alumnos inscritos y activos. Si un alumno fue dado de baja o aún no se inscribe, no aparece. La columna «Inscritos» de «Mis grupos» te dice cuántos hay."),
    # ---------- Administrativo ----------
    e(M, "¿Cómo consulto los alumnos y calificaciones de un grupo?", "consultar alumnos calificaciones grupo ver materia lista buscar",
      "En el panel, elige «Materias» en el desplegable y presiona «Siguiente». Escoge el grupo (están agrupados por materia) y presiona «Siguiente» para ver a sus alumnos.", True),
    e(M, "¿Cómo doy de baja a un alumno?", "baja alumno dar eliminar quitar inscripcion",
      "En la tabla de alumnos del grupo, marca la casilla «Baja» del alumno y presiona «Confirmar». La inscripción queda marcada como baja (no se borra) y el alumno ya no la ve.", True),
    e(M, "¿Cómo doy de baja a un profesor de una materia?", "baja profesor maestro docente materia grupo quitar desasignar",
      "En el panel elige «Profesores», marca «Baja» en el grupo que corresponda y presiona «Confirmar». El grupo queda sin profesor.", True),
    e(M, "¿Cómo creo usuarios o restablezco contraseñas?", "crear usuarios usuario contrasena contrasenas restablecer cambiar administrador alta cuenta",
      "Por ahora no hay una pantalla para eso: se hace con las herramientas de administración del proyecto, desde la terminal."),
    # ---------- Para todos ----------
    e(TODOS, "¿Con qué datos inicio sesión?", "iniciar sesion entro entrada acceder ingresar datos usuario matricula login",
      "Elige tu tipo en la lista: Alumno con tu matrícula, Profesor con tu ID de trabajador (por ejemplo P001) o Administrativo con tu usuario. Después escribe tu contraseña.", True),
    e(TODOS, "No puedo iniciar sesión, dice «Datos incorrectos»", "incorrectos incorrecto error rechaza invalida falla entrar entra puedo",
      "Revisa que el Tipo coincida con tu cuenta, que escribas tu matrícula, ID o usuario exacto (sin espacios) y tu contraseña con mayúsculas y minúsculas. Si sigue igual, pide que te la restablezcan."),
    e(TODOS, "Olvidé mi contraseña", "olvide olvido olvidaste olvidar recuperar restablecer perdi contrasena clave",
      "Por ahora la recuperación la hace el área administrativa: acude a control escolar para que te asignen una contraseña nueva."),
    e(TODOS, "¿Cómo cierro sesión?", "cerrar cierro salir sesion terminar logout",
      "Usa el botón «Cerrar sesión», arriba a la derecha. La sesión también se cierra sola después de 30 minutos sin actividad, salvo que hayas marcado «Recordarme».", True),
    e(TODOS, "¿Qué significa «Recordarme»?", "recordarme recordar mantener abierta sesion",
      "Mantiene tu sesión abierta hasta 7 días en ese equipo. No lo uses en computadoras compartidas."),
    e(TODOS, "Hola", "hola buenas buenos dias tardes noches saludos hey",
      "¡Hola! Soy el asistente del SIE. Pregúntame cómo usar el sistema o elige una de las preguntas sugeridas."),
    e(TODOS, "Gracias", "gracias muchas agradezco listo perfecto ok",
      "¡De nada! Si tienes otra duda, aquí estoy."),
    e(TODOS, "¿Qué puedes hacer?", "ayuda ayudar hacer puedes sirves funciones quien eres",
      "Resuelvo dudas frecuentes sobre el sistema: iniciar sesión, inscripciones, calificaciones, bajas y más. Escribe tu pregunta o elige una sugerida."),
]

# ---------------------------------------------------------------------------------------------
VACIAS = set("""a al ante con de del el en es esta este la las lo los me mi mis mas muy no o para pero por que se si
su sus te tu un una y ya yo como cual donde cuando puedo debo hay""".split())


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")  # quita acentos
    return re.findall(r"[a-z0-9]+", texto)


def parecidos(a, b):
    """Palabras iguales o de la misma familia (inscribo / inscribir, calificacion / calificaciones)."""
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    comun = 0
    for x, y in zip(a, b):
        if x != y:
            break
        comun += 1
    return comun >= 6


for _e in FAQ:
    _e["_p"] = [t for t in normalizar(_e["p"]) if t not in VACIAS]


def puntuar(entrada, tokens):
    puntos = 0
    for t in tokens:
        if any(parecidos(t, k) for k in entrada["k"]):
            puntos += 2
        elif any(parecidos(t, w) for w in entrada["_p"]):
            puntos += 1
    parecido = SequenceMatcher(None, " ".join(tokens), " ".join(entrada["_p"])).ratio()
    return puntos, parecido


def sugerencias_de(rol, cuantas=4):
    return [x["p"] for x in FAQ if rol in x["roles"] and x["s"]][:cuantas]


def responder(mensaje, rol):
    tokens = [t for t in normalizar(mensaje) if t not in VACIAS]
    candidatas = [x for x in FAQ if rol in x["roles"]]
    ranking = sorted(((puntuar(x, tokens), x) for x in candidatas), key=lambda c: c[0], reverse=True)
    if not tokens or not ranking or ranking[0][0][0] < UMBRAL:
        return {"respuesta": NO_ENTENDI, "sugerencias": sugerencias_de(rol)}
    mejor = ranking[0][1]
    otras = [x["p"] for (pt, _), x in ranking[1:3] if pt >= UMBRAL]
    return {"respuesta": mejor["r"], "sugerencias": otras}


# ---------------------------------------------------------------------------------------------
_historial = defaultdict(deque)


def demasiados(uid):
    ahora = time.time()
    h = _historial[uid]
    while h and ahora - h[0] > VENTANA:
        h.popleft()
    if len(h) >= LIMITE_MENSAJES:
        return True
    h.append(ahora)
    return False


def _rol():
    rol = session.get("rol")
    return rol if session.get("uid") and rol in TODOS else None


@chatbot_bp.route("/inicio")
def inicio():
    rol = _rol()
    if not rol:
        return jsonify(error="Inicia sesión para usar el asistente."), 401
    return jsonify(saludo=SALUDO, sugerencias=sugerencias_de(rol))


@chatbot_bp.route("/preguntar", methods=["POST"])
def preguntar():
    rol = _rol()
    if not rol:
        return jsonify(error="Inicia sesión para usar el asistente."), 401
    if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.get("csrf", "")):
        return jsonify(error="Solicitud no válida."), 400
    mensaje = str((request.get_json(silent=True) or {}).get("mensaje", "")).strip()
    if not mensaje or len(mensaje) > 300:
        return jsonify(error="Escribe una pregunta de hasta 300 caracteres."), 400
    if demasiados(session["uid"]):
        return jsonify(error="Has enviado muchos mensajes. Espera unos minutos e inténtalo de nuevo."), 429
    return jsonify(**responder(mensaje, rol))
