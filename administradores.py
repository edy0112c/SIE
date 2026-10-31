"""Crea o borra usuarios administrativos.

  python administradores.py crear 5 [dominio]     -> crea Admin1..Admin5 (o los siguientes libres)
  python administradores.py borrar correo@x.com   -> borra un usuario por su correo

Para entrar al sistema: Tipo = Administrativo, usuario = Admin1 (respeta mayúsculas) y su contraseña.
Las contraseñas se guardan en contrasenas_administradores.csv (local, no se sube a GitHub).
"""
import csv
import os
import secrets
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])

ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def nueva_contrasena():
    while True:
        clave = "".join(secrets.choice(ALFABETO) for _ in range(10))
        if any(c.isdigit() for c in clave) and any(c.islower() for c in clave) and any(c.isupper() for c in clave):
            return clave


def crear(cantidad, dominio):
    existentes = {u["usuario"] for u in db.table("usuarios").select("usuario").execute().data}
    correos_auth = {u.email for u in db.auth.admin.list_users(per_page=1000)}
    filas, numero = [], 0
    while len(filas) < cantidad:
        numero += 1
        usuario, correo = f"Admin{numero}", f"admin{numero}@{dominio}"
        if usuario in existentes or correo in correos_auth:
            continue
        clave = nueva_contrasena()
        creado = db.auth.admin.create_user({"email": correo, "password": clave, "email_confirm": True})
        uid = creado.user.id
        try:
            db.table("usuarios").insert({
                "id_usuario": uid, "correo": correo, "rol": "administrador", "usuario": usuario,
                "fecha_registro": datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}).execute()
        except Exception as error:
            db.auth.admin.delete_user(uid)  # no dejar cuentas a medias
            sys.exit(f"No se pudo registrar {usuario} en la tabla usuarios: {error}")
        filas.append([usuario, correo, clave])
        print("  creado:", usuario, "|", correo)
    archivo = "contrasenas_administradores.csv"
    nuevo = not os.path.exists(archivo)
    with open(archivo, "a", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f)
        if nuevo:
            escritor.writerow(["usuario_para_entrar", "correo", "contrasena"])
        escritor.writerows(filas)
    print(f"Listo: {len(filas)} administradores. Contraseñas en {archivo}")


def borrar(correo):
    filas = db.table("usuarios").select("id_usuario,rol,usuario").eq("correo", correo).execute().data
    en_auth = next((u for u in db.auth.admin.list_users(per_page=1000) if u.email == correo), None)
    if not filas and not en_auth:
        sys.exit("Ese correo no existe ni en la tabla usuarios ni en Authentication.")
    for u in filas:  # no borrar a alguien que ya tiene perfil de alumno o profesor
        for tabla in ("alumnos", "profesores"):
            perfil = db.table(tabla).select("nombre_completo").eq("id_usuario", u["id_usuario"]).execute().data
            if perfil:
                sys.exit(f"{correo} pertenece a {perfil[0]['nombre_completo']} ({tabla}). "
                         "No se borra para no dejar ese perfil sin cuenta.")
    print(f"Se va a borrar {correo}: {len(filas)} fila(s) en usuarios y "
          f"{'1 cuenta' if en_auth else '0 cuentas'} en Authentication.")
    if input("Escribe SI para continuar: ").strip() != "SI":
        sys.exit("Cancelado, no se borró nada.")
    for u in filas:
        db.table("usuarios").delete().eq("id_usuario", u["id_usuario"]).execute()
    if en_auth:
        db.auth.admin.delete_user(en_auth.id)
    print("Borrado.")


if __name__ == "__main__":
    orden = sys.argv[1:2]
    if orden == ["crear"] and len(sys.argv) >= 3 and sys.argv[2].isdigit():
        crear(int(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "sie-prueba.com")
    elif orden == ["borrar"] and len(sys.argv) == 3:
        borrar(sys.argv[2])
    else:
        sys.exit(__doc__)
