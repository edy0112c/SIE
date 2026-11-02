// SIE · Interacciones de la maqueta (sin base de datos todavía)
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// Un botón con data-necesita="selector,selector" se activa cuando todos tienen valor / están marcados
function listo(b) {
  return b.dataset.necesita.split(",").every(s => {
    const e = document.querySelector(s.trim());
    return e && (e.tagName !== "SELECT" || e.value);
  });
}
const refrescar = () => $$("[data-necesita]").forEach(b => b.disabled = !listo(b));

// Un desplegable con data-filtra="#caja" muestra solo las filas de la materia elegida
$$("[data-filtra]").forEach(sel => {
  const caja = document.querySelector(sel.dataset.filtra);
  const filtrar = () => {
    $$("tbody tr", caja).forEach(tr => {
      tr.hidden = tr.dataset.materia !== sel.value;
      if (tr.hidden) $$("input", tr).forEach(i => i.checked = false);
    });
    caja.hidden = !sel.value;
    refrescar();
  };
  sel.addEventListener("change", filtrar);
  filtrar();
});

// Un desplegable con data-depende="#materia" solo ofrece los grupos de esa materia
$$("[data-depende]").forEach(g => {
  const m = document.querySelector(g.dataset.depende);
  const todas = $$("option[data-materia]", g);
  const llenar = () => {
    g.length = 1;
    todas.filter(o => o.dataset.materia === m.value).forEach(o => g.add(o.cloneNode(true)));
    g.value = "";
    g.disabled = !m.value;
    refrescar();
  };
  m.addEventListener("change", llenar);
  llenar();
});

$$("[data-ir]").forEach(b => b.addEventListener("click", () => { location.href = b.dataset.ir; }));
// Un botón con data-ir-select="#lista" va a la dirección elegida en ese desplegable
$$("[data-ir-select]").forEach(b => b.addEventListener("click", () => {
  const v = document.querySelector(b.dataset.irSelect).value;
  if (v) location.href = v;
}));
$$("[data-aviso]").forEach(b => b.addEventListener("click", () => {
  const t = document.getElementById("toast");
  t.textContent = b.dataset.aviso; t.hidden = false;
  setTimeout(() => { t.hidden = true; }, 2200);
}));
document.addEventListener("change", refrescar);
refrescar();
