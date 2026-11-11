// SIE · Asistente de ayuda: ventana de chat que consulta /chatbot (preguntas frecuentes)
(() => {
  const raiz = document.getElementById("sie-chatbot");
  if (!raiz) return;
  const { csrf, inicio, preguntar } = raiz.dataset;

  raiz.innerHTML = `
    <button class="cb-boton" type="button" aria-expanded="false" aria-controls="cb-panel">💬 Ayuda</button>
    <section class="cb-panel" id="cb-panel" aria-label="Asistente del SIE" hidden>
      <header><b>Asistente SIE</b><button class="cb-cerrar" type="button" aria-label="Cerrar asistente">×</button></header>
      <div class="cb-mensajes" role="log" aria-live="polite"></div>
      <div class="cb-sug"></div>
      <form class="cb-form"><input type="text" maxlength="300" placeholder="Escribe tu duda…" aria-label="Tu pregunta" autocomplete="off"><button type="submit">Enviar</button></form>
    </section>`;

  const boton = raiz.querySelector(".cb-boton");
  const panel = raiz.querySelector(".cb-panel");
  const mensajes = raiz.querySelector(".cb-mensajes");
  const sugerencias = raiz.querySelector(".cb-sug");
  const form = raiz.querySelector(".cb-form");
  const campo = form.querySelector("input");
  let iniciado = false;

  function agregar(texto, quien) {
    const d = document.createElement("div");
    d.className = "cb-msg " + (quien === "yo" ? "cb-yo" : "cb-bot");
    d.textContent = texto;               // textContent: nunca se interpreta como HTML
    mensajes.appendChild(d);
    mensajes.scrollTop = mensajes.scrollHeight;
  }

  function mostrarSugerencias(lista) {
    sugerencias.replaceChildren();
    (lista || []).forEach(t => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = t;
      b.addEventListener("click", () => enviar(t));
      sugerencias.appendChild(b);
    });
  }

  async function enviar(texto) {
    texto = texto.trim();
    if (!texto) return;
    agregar(texto, "yo");
    campo.value = "";
    mostrarSugerencias([]);
    try {
      const r = await fetch(preguntar, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ mensaje: texto }),
      });
      const datos = await r.json();
      if (!r.ok) { agregar(datos.error || "No pude responder en este momento.", "bot"); return; }
      agregar(datos.respuesta, "bot");
      mostrarSugerencias(datos.sugerencias);
    } catch (e) {
      agregar("No pude conectar con el asistente. Revisa tu conexión e inténtalo de nuevo.", "bot");
    }
  }

  async function abrir() {
    panel.hidden = false;
    boton.setAttribute("aria-expanded", "true");
    campo.focus();
    if (iniciado) return;
    iniciado = true;
    try {
      const datos = await (await fetch(inicio)).json();
      agregar(datos.saludo || datos.error, "bot");
      mostrarSugerencias(datos.sugerencias);
    } catch (e) {
      agregar("No pude conectar con el asistente.", "bot");
    }
  }

  function cerrar() { panel.hidden = true; boton.setAttribute("aria-expanded", "false"); boton.focus(); }

  boton.addEventListener("click", () => (panel.hidden ? abrir() : cerrar()));
  raiz.querySelector(".cb-cerrar").addEventListener("click", cerrar);
  panel.addEventListener("keydown", e => { if (e.key === "Escape") cerrar(); });
  form.addEventListener("submit", e => { e.preventDefault(); enviar(campo.value); });
})();
