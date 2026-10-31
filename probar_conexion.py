"""Comprueba que Python se conecta a Supabase y cuenta las filas de cada tabla."""
import os

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
cliente = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SECRET_KEY"])

TABLAS = ("usuarios", "alumnos", "profesores", "materias", "grupos", "inscripciones", "calificaciones")
for tabla in TABLAS:
    try:
        r = cliente.table(tabla).select("*", count="exact").limit(1).execute()
        print(f"{tabla}: {r.count} filas")
    except Exception as e:
        print(f"{tabla}: ERROR -> {e}")  