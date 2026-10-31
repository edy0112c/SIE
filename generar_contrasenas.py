"""Genera una contraseña DISTINTA para cada usuario y las guarda en un CSV local.

Uso:  python generar_contrasenas.py alumno|profesor|administrador|todos

El CSV (contrasenas_<rol>.csv) trae el usuario para entrar y su contraseña. Entrégalas
a cada persona por separado y borra el archivo después. No se sube a GitHub (*.csv).
Si lo vuelves a ejecutar, las contraseñas anteriores dejan de funcionar.
"""
import csv
import os
import secrets
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])

# Sin letras ni números que se confunden (0/O, 1/l/I)
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def nueva_contrasena():
    while True:
        clave = "".join(secrets.choice(ALFABETO) for _ in range(10))
        if any(c.isdigit() for c in clave) and any(c.islower() for c in clave) and any(c.isupper() for c in clave):
            return clave


rol = sys.argv[1] if len(sys.argv) > 1 else ""
if rol not in ("alumno", "profesor", "administrador", "todos"):
    sys.exit("Uso: python generar_contrasenas.py alumno|profesor|administrador|todos")

usuarios = db.table("usuarios").select("id_usuario,correo,rol,usuario").execute().data
if rol != "todos":
    usuarios = [u for u in usuarios if u["rol"] == rol]

# Con qué escribe cada persona su usuario al iniciar sesión
identificador = {a["id_usuario"]: (a["matricula"], a["nombre_completo"])
                 for a in db.table("alumnos").select("id_usuario,matricula,nombre_completo").execute().data}
identificador.update({p["id_usuario"]: (p["num_empleado"], p["nombre_completo"])
                      for p in db.table("profesores").select("id_usuario,num_empleado,nombre_completo").execute().data})

# Cuentas que existen en Supabase Auth
en_auth, pagina = {}, 1
while True:
    lote = db.auth.admin.list_users(page=pagina, per_page=100)
    en_auth.update({u.email: u.id for u in lote})
    if len(lote) < 100:
        break
    pagina += 1

print(f"Se van a cambiar las contraseñas de {len(usuarios)} usuario(s) ({rol}).")
if input("Escribe SI para continuar: ").strip() != "SI":
    sys.exit("Cancelado, no se cambió nada.")

filas = []
for u in usuarios:
    uid = en_auth.get(u["correo"])
    if not uid:
        print("  SIN CUENTA EN AUTH, se omite:", u["correo"])
        continue
    clave = nueva_contrasena()
    db.auth.admin.update_user_by_id(uid, {"password": clave})
    entrar_con, nombre = identificador.get(u["id_usuario"], (u["usuario"], u["usuario"]))
    filas.append([u["rol"], entrar_con, nombre, u["correo"], clave])

archivo = f"contrasenas_{rol}.csv"
with open(archivo, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig: Excel lee bien los acentos
    csv.writer(f).writerows([["rol", "usuario_para_entrar", "nombre", "correo", "contrasena"], *filas])
print(f"Listo: {len(filas)} contraseñas nuevas guardadas en {archivo}")