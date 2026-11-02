// Panel de monitoreo.
const TIPOS = { norma: "Norma", pl: "Proyecto", noticia: "Noticia" };

VISTAS.panel = (() => {
  const nom = "panel";
  let d, raiz, filas = [], proyectos = [], agenda = [], sesiones = [], sel = null;
  const s = () => App.f(nom, { pais: "Todos", cli: "", ven: "Desde ayer 4 p. m.", tab: "alertas", tipo: "Todas", q: "", etapa: null, orden: ["cambio", -1] });
  const igual = (a, b) => !!a && !!b && a.titulo === b.titulo && a.url === b.url;

  function filtrar() {
    const f = s();
    const v = d.ventanas[f.ven];
    const paises = Object.keys(PAISES).filter((p) => f.pais === "Todos" || PAISES[p] === f.pais);
    const slugs = f.cli ? [f.cli] : Object.keys(App.d.clientes);
    const cubre = new Set(slugs.flatMap((c) => App.d.clientes[c].paises));
    const q = (f.q ?? "").toLowerCase();
    const todas = v.alertas.filter((a) => paises.includes(a.pais)
      && (a.tipo === "norma" && !Object.keys(a.porque).length ? cubre.has(a.pais) : Object.keys(a.porque).some((c) => slugs.includes(c)))
      && !App.fuera.has(a.id));
    filas = todas.filter((a) => (f.tipo === "Todas" || TIPOS[a.tipo] === f.tipo)
      && (!q || `${a.titulo} ${a.fuente} ${a.tema ?? ""}`.toLowerCase().includes(q)));
    proyectos = d.proyectos.filter((p) => paises.includes(p.pais) && p.clientes.some((c) => slugs.includes(c)));
    agenda = d.agenda.filter((a) => paises.includes(a.pais));
    sesiones = v.sesiones.filter((x) => paises.includes(x.pais));
    return { v, todas, paises, total: paises.reduce((n, p) => n + d.total_tramite[p], 0) };
  }

  function fila(a, i) {
    const f = s();
    const clientes = Object.keys(a.porque).filter((c) => !f.cli || c === f.cli);
    let porque = a.porque[clientes[0]] || (a.resumen || "").slice(0, 200);
    if (porque.slice(0, 40).toLowerCase() === a.titulo.slice(0, 40).toLowerCase()) porque = "";  // las normas traen el titulo como resumen
    const otras = a.otras.length ? `, también en ${a.otras.length} fuente${a.otras.length > 1 ? "s" : ""} más` : "";
    return `<article class="fila ${a.tipo}${igual(sel, a) ? " activa" : ""}" data-i="${i}" tabindex="0">
      <div class="marcas"><span>${TIPOS[a.tipo]}</span><span>${PAISES[a.pais] ?? esc(a.pais)}</span>${a.tema ? `<span>${esc(a.tema)}</span>` : ""}
      ${clientes.map((c) => `<span class="cli">${esc(App.nombre(c))}</span>`).join("")}
      ${enlace(a.url, "Abrir fuente", "fuente")}</div>
      <h3>${esc(a.titulo)}</h3>${porque ? `<p>${esc(porque)}</p>` : ""}<small>${esc(a.fuente)}${otras}</small></article>`;
  }

  let tope = PASO;
  function vistaAlertas(animar) {
    const f = s();
    const caja = raiz.querySelector(".vista");
    if (!caja.querySelector(".lista")) {
      caja.innerHTML = `<div class="barra"><div class="f-tipo"></div><input class="buscar" type="search" placeholder="Filtrar esta lista (tecla /)" aria-label="Filtrar esta lista"></div><div class="lista"></div>`;
      segmentado(caja.querySelector(".f-tipo"), ["Todas", ...Object.values(TIPOS)], f.tipo, (t) => { f.tipo = t; tope = PASO; dibujar(true); });
      const q = caja.querySelector(".buscar");
      q.value = f.q ?? "";
      q.oninput = () => { f.q = q.value; tope = PASO; dibujar(false); };
    }
    const lista = caja.querySelector(".lista");
    if (!filas.length) { lista.innerHTML = `<div class="vacio">Nada relevante con estos filtros. Prueba un periodo más largo u otro cliente.</div>`; return; }
    lista.innerHTML = filas.slice(0, tope).map(fila).join("")
      + (filas.length > tope ? `<button type="button" class="mas">Ver las ${filas.length - tope} restantes</button>` : "");
    if (animar) entrar(lista.querySelectorAll(".fila"));
  }

  function vistaProyectos() {
    const f = s();
    const caja = raiz.querySelector(".vista");
    const conteo = d.etapas.map((_, i) => proyectos.filter((p) => p.etapa === i).length);
    const max = Math.max(...conteo, 1);
    caja.innerHTML = `<div class="embudo">${d.etapas.map((e, i) => `<button type="button" class="etapa" data-etapa="${i}" aria-pressed="${f.etapa === i}">
        <b>${conteo[i]}</b>${esc(e)}<u style="transform:scaleX(${conteo[i] / max})"></u></button>`).join("")}</div><div class="t-proy"></div>`;
    const cols = [
      { k: "pais", t: "País" }, { k: "numero", t: "Número", f: (p) => enlace(p.url, p.numero) || esc(p.numero) },
      { k: "titulo", t: "Proyecto" }, { k: "etapa", t: "Etapa", f: (p) => esc(d.etapas[p.etapa]) },
      { k: "clientes", t: "Clientes", f: (p) => p.clientes.filter((c) => !f.cli || c === f.cli).map((c) => esc(App.nombre(c))).join(", ") },
      { k: "cambio", t: "Último cambio", f: (p) => esc(fechaCorta(p.cambio)) },
    ];
    tabla(caja.querySelector(".t-proy"), { cols, filas: proyectos.filter((p) => f.etapa === null || p.etapa === f.etapa), orden: f.orden,
      alOrdenar: (o) => { f.orden = o; dibujar(false); }, vacio: "Ningún proyecto de estos clientes en esta etapa." });
  }

  function lado() {
    const conTema = agenda.filter((a) => a.puntos.length);
    const resto = agenda.filter((a) => !a.puntos.length);
    const ag = (a) => `<div class="ag">${esc(a.nombre)}<small>${esc(a.cuando)}, ${PAISES[a.pais]}</small>${a.puntos.slice(0, 3).map((p) => `<p>${esc(p)}</p>`).join("")}</div>`;
    raiz.querySelector(".lado").innerHTML = `<section><h2>Agenda con temas de interés</h2>
        ${conTema.length ? conTema.slice(0, 8).map(ag).join("") : `<p class="nota">Sin temas de interés en las ${agenda.length} sesiones convocadas.</p>`}
        ${resto.length ? `<details><summary>Otras ${resto.length} sesiones convocadas</summary>${resto.map(ag).join("")}</details>` : ""}</section>
      <section><h2>Sesiones resumidas</h2>
        ${sesiones.length ? sesiones.map((x, i) => `<button type="button" class="ses" data-ses="${i}">${esc(x.titulo)}</button>`).join("") : `<p class="nota">Ninguna sesión nueva en este periodo.</p>`}</section>`;
  }

  function detalle(a) {
    sel = a;
    const f = s();
    const clientes = Object.keys(a.porque ?? {});
    const elegido = f.cli || clientes[0] || "";
    const it = item(a.titulo, a.url, a.resumen, a.pais, a.fuente, a.fecha, a.tipo);
    const det = App.detalle(`
      <div class="marcas">${[TIPOS[a.tipo] ?? "Sesión", PAISES[a.pais], a.fuente, ...(a.otras ?? [])].filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("")}</div>
      <h2>${esc(a.titulo)}</h2>
      ${clientes.map((c) => `<div class="por"><b>${esc(App.nombre(c))}</b>${esc(a.porque[c])}</div>`).join("")}
      ${a.resumen && !clientes.length ? `<p>${esc(a.resumen.slice(0, 900))}</p>` : ""}
      ${a.ideas?.length ? `<ul>${a.ideas.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
      <div class="acciones">${enlace(a.url, a.tipo === "sesion" ? "Ver el video" : "Abrir la fuente", "btn pri")}
        ${bloqueArmar([it], elegido)}
        ${a.id != null ? `<button type="button" class="btn des d-descartar">Descartar esta noticia</button>` : ""}</div>`);
    conectarArmar(det, [it], (c) => a.porque?.[c] ?? null);
    const des = det.querySelector(".d-descartar");
    if (des) des.onclick = () => descartar(a.id, a.titulo, () => dibujar(false));
    App.alCerrar = () => { sel = null; marcar(); };
    marcar();
  }

  function marcar() {
    raiz?.querySelectorAll(".fila").forEach((el) => el.classList.toggle("activa", igual(filas[el.dataset.i], sel)));
  }

  function dibujar(animar) {
    if (!raiz?.isConnected) return;
    App.recordar(nom, ["q"]);
    const f = s();
    const r = filtrar();
    const conPuntos = agenda.filter((a) => a.puntos.length).length;
    kpis(raiz.querySelector(".kpis"), [
      [r.paises.reduce((n, p) => n + (r.v.entradas[p] ?? 0), 0), "Documentos revisados", f.ven],
      [r.todas.length, "Relevantes para clientes", f.cli ? App.nombre(f.cli) : `${r.todas.filter((a) => a.tipo === "norma").length} normas`],
      [proyectos.length, "Proyectos de clientes", `de ${miles(r.total)} en trámite`],
      [r.todas.filter((a) => a.tipo === "pl").length, "Proyectos que se movieron", f.ven],
      [agenda.length, `Sesiones en ${d.dias_agenda} días`, `${conPuntos} con temas de interés`],
    ]);
    pestanas(raiz.querySelector(".tabs"), [["alertas", `Alertas (${filas.length})`], ["proyectos", `Proyectos de clientes (${proyectos.length})`]], f.tab, (t) => {
      f.tab = t; raiz.querySelector(".vista").innerHTML = ""; dibujar(true);
    });
    if (f.tab === "alertas") vistaAlertas(animar); else vistaProyectos();
    lado();
  }

  function subtitulo() {
    App.$(".sub").innerHTML = `${esc(d.ahora)} en Lima, ${d.atrasada ? `<b>${esc(d.ultima)}</b>` : esc(d.ultima)}`;
  }

  return {
    titulo: "Panel de monitoreo", seccion: "panel",
    async abrir(cuerpo, ctrl) {
      raiz = cuerpo;
      cuerpo.innerHTML = espera();
      d = await App.seccion(nom);
      if (App.ruta !== nom) return;
      subtitulo();
      const f = s();
      if (!d.ventanas[f.ven]) f.ven = Object.keys(d.ventanas)[0];
      ctrl.innerHTML = `<div class="f-pais"></div><div class="f-cli"></div><div class="f-ven"></div>`;
      segmentado(ctrl.querySelector(".f-pais"), ["Todos", ...Object.values(PAISES)], f.pais, (t) => { f.pais = t; tope = PASO; dibujar(true); });
      segmentado(ctrl.querySelector(".f-ven"), Object.keys(d.ventanas), f.ven, (t) => { f.ven = t; tope = PASO; dibujar(true); });
      botonesCliente(ctrl.querySelector(".f-cli"), Object.keys(App.d.clientes), f.cli, (v) => { f.cli = v; tope = PASO; dibujar(true); });
      cuerpo.innerHTML = `<div class="aviso"${d.sin_cerebro ? "" : " hidden"}>Todavía no carga la base de relevancia, así que faltan las noticias.</div>
        <div class="kpis"></div><div class="dos"><div><div class="tabs" role="tablist"></div><div class="vista"></div></div><div class="lado"></div></div>`;
      cuerpo.onclick = (e) => {
        const t = e.target;
        if (t.closest("a")) return;
        const fi = t.closest(".fila");
        if (fi) { const a = filas[fi.dataset.i]; return igual(a, sel) ? App.cerrarDetalle() : detalle(a); }
        if (t.closest(".lista .mas")) { tope += PASO; return dibujar(false); }
        const et = t.closest("[data-etapa]");
        if (et) { const n = Number(et.dataset.etapa); f.etapa = f.etapa === n ? null : n; return dibujar(false); }
        const ses = t.closest("[data-ses]");
        if (ses) return detalle(sesiones[ses.dataset.ses]);
      };
      dibujar(true);
    },
    nuevos(datos) { d = datos; subtitulo(); dibujar(false); },
    tecla(e) {
      if (s().tab !== "alertas" || !"jk".includes(e.key)) return;
      const i = Math.max(0, Math.min(filas.length - 1, filas.findIndex((a) => igual(a, sel)) + (e.key === "j" ? 1 : -1)));
      if (i >= tope) { tope += PASO; dibujar(false); }
      if (!filas[i]) return;
      detalle(filas[i]);
      raiz.querySelector(`.fila[data-i="${i}"]`)?.scrollIntoView({ block: "nearest" });
    },
  };
})();

// Descartar con deshacer: lo usan el Panel y Noticias.
function descartar(id, titulo, alCambiar) {
  App.fuera.add(id);
  App.pedir("descartar", { id }).catch((e) => App.fallo(e));
  App.cerrarDetalle();
  alCambiar();
  App.aviso(`Descartaste: ${titulo}`, () => {
    App.fuera.delete(id);
    App.pedir("deshacer", { id }).catch((e) => App.fallo(e));
    alCambiar();
  });
}
