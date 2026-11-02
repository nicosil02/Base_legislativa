// Proyectos de ley de Peru y Ecuador. Mismos filtros de las paginas anteriores,
// pero sobre todos los proyectos ya cargados en el navegador.
function vistaProyectos(pais) {
  const nom = `proyectos_${pais.toLowerCase()}`;
  const pe = pais === "PE";
  let d, raiz, activa = null;
  const s = () => App.f(nom, { pl: "", cli: "", tema: "", estado: "", camara: "", comision: "", bancada: "", proponente: "", autor: "", tipo_prop: "",
                               q: "", ini: "", fin: "", unif: false, orden: ["presentado", -1] });
  const camaraTipos = { Congreso: ["Ordinaria", "Bicameral"], Diputados: ["Diputados"], Senado: ["Senado"] };

  function filtrar() {
    const f = s();
    const q = (f.q ?? "").toLowerCase();
    const pl = (f.pl ?? "").toLowerCase();
    return d.filas.filter((p) => (!pl || String(p.pl).toLowerCase().includes(pl)) && (!f.tema || p.tema === f.tema) && (!f.estado || p.estado === f.estado)
      && (!f.cli || f.cli in p.clientes) && (!q || (p.titulo ?? "").toLowerCase().includes(q))
      && (!f.ini || (p.presentado ?? "") >= f.ini) && (!f.fin || (p.presentado ?? "") <= f.fin)
      && (!f.comision || (pe ? p.comisiones.includes(f.comision) : p.comision === f.comision))
      && (pe ? (!f.camara || p.camara === f.camara) && (!f.bancada || p.bancada === f.bancada) && (!f.proponente || p.proponente === f.proponente)
              && (!f.autor || p.autores.includes(f.autor))
        : (!f.tipo_prop || p.tipo_prop === f.tipo_prop) && (!f.proponente || p.proponentes.includes(f.proponente)) && (!f.unif || p.es_unificado)));
  }

  function opcionesComision() {
    const f = s();
    if (!pe) return unicos(d.filas.map((p) => p.comision));
    const tipos = camaraTipos[f.camara];
    return [...unicos(d.comisiones.filter((c) => !tipos || tipos.includes(c.tipo)).map((c) => c.nombre)), d.especiales];
  }

  function pintarTabla() {
    const f = s();
    App.recordar(nom, ["q", "pl"]);
    const filas = filtrar();
    const cuenta = raiz.querySelector(".r-cuenta");
    const mat = f.cli ? filas.filter((p) => p.clientes[f.cli]?.[2]).length : 0;
    cuenta.textContent = `${plural(filas.length, "proyecto")} de ${miles(d.filas.length)}${mat ? `, ${mat} en la matriz de seguimiento` : ""}`;
    const nivel = f.cli ? [{ k: "rel", t: "Relevancia", ord: (p) => -(p.clientes[f.cli]?.[1] ?? -1), f: (p) => esc(p.clientes[f.cli]?.[0] ?? "") }] : [];
    const cols = pe
      ? [{ k: "pl", t: "PL", f: (p) => enlace(p.url, String(p.pl).split("-")[0].replace(/^0+/, "") || p.pl) }, ...nivel, { k: "camara", t: "Cámara" },
        { k: "titulo", t: "Título", f: (p) => `<span class="corta">${esc(p.titulo)}</span>` }, { k: "presentado", t: "Presentado", f: (p) => esc(fechaCorta(p.presentado)) },
        { k: "estado", t: "Estado" }, { k: "autor", t: "Autor" }, { k: "bancada", t: "Bancada" }, { k: "comision", t: "Comisión" }, { k: "tema", t: "Tema" }]
      : [{ k: "pl", t: "N. Trámite", f: (p) => enlace(p.url, p.pl) || esc(p.pl) }, ...nivel,
        { k: "titulo", t: "Título", f: (p) => `<span class="corta">${esc(p.titulo)}</span>` }, { k: "presentado", t: "Presentado", f: (p) => esc(fechaCorta(p.presentado)) },
        { k: "estado", t: "Estado" }, { k: "tipo_prop", t: "Tipo" }, { k: "proponente", t: "Proponente" }, { k: "comision", t: "Comisión" }, { k: "tema", t: "Tema" },
        { k: "unificado", t: "Unificado con" }];
    if (f.cli && f.orden[0] === "presentado" && !f.ordenManual) f.orden = ["rel", 1];
    if (!f.cli && f.orden[0] === "rel") f.orden = ["presentado", -1];
    const caja = raiz.querySelector(".t-pl");
    caja.tope = PASO;
    tabla(caja, { cols, filas, orden: f.orden, clic: detalle, activa: (p) => p === activa,
      alOrdenar: (o) => { f.orden = o; f.ordenManual = true; pintarTabla(); }, vacio: "Ningún proyecto con estos filtros." });
  }

  function detalle(p) {
    activa = p;
    const titulo = `PL ${p.pl}: ${p.titulo}`;
    const it = item(titulo, p.url, `Estado: ${p.estado}`, pais, null, null, "pl");
    const elegido = s().cli || Object.keys(p.clientes)[0] || "";
    const dato = (t, v) => (v ? `<div class="dato"><span>${esc(t)}</span>${esc(v)}</div>` : "");
    const det = App.detalle(`<div class="marcas"><span>${esc(p.estado)}</span><span>${esc(p.tema)}</span>${Object.keys(p.clientes).map((c) => `<span class="cli">${esc(App.nombre(c))}</span>`).join("")}</div>
      <h2>${esc(p.titulo)}</h2>
      ${dato(pe ? "Proyecto" : "N. Trámite", p.pl)}${dato("Presentado", fechaCorta(p.presentado))}${dato("Último cambio", fechaCorta(p.cambio))}${dato("Cámara", p.camara)}${dato("Comisión", p.comision)}
      ${dato("Bancada", p.bancada)}${dato(pe ? "Autores" : "Proponentes", pe ? p.autores : p.proponentes)}
      <div class="acciones">${enlace(p.url, pe ? "Abrir en el Congreso" : "Abrir el proyecto", "btn pri")}${pe ? enlace(p.pdf, "Ver PDF", "btn") : ""}${bloqueArmar([it], elegido, null, d.clientes)}</div>
      <div class="d-extra"></div>`);
    conectarArmar(det, [it]);
    App.alCerrar = () => { activa = null; };
    if (!pe) documentos(det.querySelector(".d-extra"), p);
  }

  async function documentos(caja, p) {
    caja.innerHTML = `<p class="nota">Buscando documentos…</p>`;
    try {
      const r = await App.pedir("pl_ec", { pl: p.pl });
      if (!caja.isConnected) return;
      caja.innerHTML = `${r.marcado ? `<p class="nota">Marcado como unificado en el portal.</p>` : ""}
        ${r.grupo ? `<details><summary>Grupo de unificación: ${esc(r.grupo.nombre || "sin nombre")} (${r.grupo.miembros.length})</summary>
          ${r.grupo.descripcion ? `<p class="nota">${esc(r.grupo.descripcion)}</p>` : ""}
          ${r.grupo.miembros.map((m) => `<div class="ag">${m.pl === r.grupo.principal ? "Principal: " : ""}${esc(m.pl)}<small>${esc(m.titulo)}, ${esc(m.estado)}</small></div>`).join("")}</details>` : ""}
        <h3 class="sub-t">Documentos</h3>
        ${r.docs.length ? r.docs.map((x) => `<div class="ag">${enlace(x.url, x.descripcion) || esc(x.descripcion)}<small>${esc(x.fase)}</small></div>`).join("") : `<p class="nota">Todavía no tiene documentos enriquecidos.</p>`}`;
    } catch (e) { caja.innerHTML = `<p class="nota">No se pudieron traer los documentos: ${esc(e.message)}</p>`; }
  }

  function sync() {
    if (!pe) {
      const l = d.sync;
      return `Actualizado por el workflow cada 4 a 6 horas${l?.finished_at ? `, última corrida ${esc(fechaCorta(l.finished_at))}` : ""}`;
    }
    const x = d.sync;
    if (x.corriendo) return "Buscando proyectos nuevos…";
    if (!x.ultimo) return "Sin sincronizaciones previas";
    const m = x.minutos;
    const hace = m == null ? "" : m < 60 ? `hace ${Math.floor(m)} min` : m < 1440 ? `hace ${Math.floor(m / 60)} h` : `hace ${Math.floor(m / 1440)} d`;
    return `Actualizado ${hace}. Último ciclo: ${x.ultimo.proyectos_nuevos} nuevos, ${x.ultimo.proyectos_actualizados} actualizados, ${x.ultimo.errores} errores`;
  }

  function sugerencias(caja) {
    const lista = d.sugerencias ?? [];
    if (!lista.length) { caja.hidden = true; return; }
    caja.hidden = false;
    caja.innerHTML = `<details><summary>Sugerencias de reclasificación pendientes (${lista.length})</summary>
      <p class="nota">El clasificador detecta proyectos en "Otros" que probablemente son de otro tema. Se aplica en la próxima sincronización.</p>
      ${lista.map((x) => `<div class="suger" data-s="${x.id}"><div><b>PL ${esc(x.pley_num)}</b> ${esc(x.tema_anterior)} a ${esc(x.tema_sugerido)} (${Math.round(x.confidence * 100)}%)<small>${esc(x.titulo)}</small></div>
        <button type="button" class="btn" data-d="aceptar">Aceptar</button><button type="button" class="btn" data-d="rechazar">Rechazar</button></div>`).join("")}</details>`;
    caja.onclick = async (e) => {
      const b = e.target.closest("[data-d]");
      if (!b) return;
      const id = Number(b.closest(".suger").dataset.s);
      try {
        await App.pedir("sugerencia", { id, decision: b.dataset.d });
        d.sugerencias = d.sugerencias.filter((x) => x.id !== id);
        sugerencias(caja);
      } catch (err) { App.fallo(err); }
    };
  }

  function abrirVista(cuerpo) {
    const f = s();
    const prop = pe ? unicos(d.filas.map((p) => p.proponente)) : unicos(d.filas.flatMap((p) => p.proponentes.split("/").map((x) => x.split("(")[0].trim()))).filter((x) => x !== "—");
    const opc = (t, k, ops, todos) => campoFiltro({ k, t, todos: todos ?? t, ops }, f);
    const masPe = () => `${opc("Cámara", "camara", unicos(d.filas.map((p) => p.camara)), "Toda cámara")}<span class="f-com"></span>
      ${opc("Bancada", "bancada", unicos(d.filas.map((p) => p.bancada)), "Toda bancada")}${opc("Proponente", "proponente", prop, "Todo proponente")}
      ${opc("Autor", "autor", unicos(d.filas.flatMap((p) => p.autores.split(";").map((x) => x.trim()))), "Todo autor")}`;
    const masEc = () => `<span class="f-com"></span>${opc("Tipo de proponente", "tipo_prop", unicos(d.filas.map((p) => p.tipo_prop)), "Todo tipo de proponente")}
      ${opc("Proponente", "proponente", prop, "Todo proponente")}${campoFiltro({ k: "unif", t: "Solo unificados", tipo: "check" }, f)}`;
    cuerpo.innerHTML = `<div class="kpis"></div>
      <div class="dos dos-g"><div>${evolucion(d.evolucion)}</div><div class="lado"><h2>Estado de los datos</h2><p class="nota">${sync()}</p>
        ${pe ? `<button type="button" class="btn r-live">Buscar proyectos nuevos en el Congreso</button><div class="r-res"></div>` : ""}
        ${d.candidatas?.length ? `<details><summary>${d.candidatas.length} noticias de la Asamblea que podrían ser avance de trámite</summary>
          <p class="nota">Suelen salir antes que el portal oficial. Revísalas a mano.</p>
          ${d.candidatas.map((c) => `<div class="ag">${enlace(c.url, c.titulo)}<small>${esc(fechaCorta(c.fecha_pub))}</small></div>`).join("")}</details>` : ""}</div></div>
      <div class="r-sug" hidden></div>
      <div class="barra"><div class="f-cli"></div></div>
      <div class="barra filtros">${campoFiltro({ k: "pl", t: pe ? "N.º de PL" : "N. Trámite", tipo: "texto" }, f)}
        ${opc("Tema", "tema", unicos(d.filas.map((p) => p.tema)), "Todo tema")}${opc("Estado", "estado", unicos(d.filas.map((p) => p.estado)), "Todo estado")}
        ${campoFiltro({ k: "q", t: "Buscar en el título (tecla /)", tipo: "texto" }, f)}
        <details class="mas-f"><summary>Más filtros</summary><div class="barra">${pe ? masPe() : masEc()}
          ${campoFiltro({ k: "ini", t: "Desde", tipo: "fecha" }, f)}${campoFiltro({ k: "fin", t: "Hasta", tipo: "fecha" }, f)}</div></details></div>
      <p class="r-cuenta nota"></p><div class="t-pl"></div>`;
    kpis(cuerpo.querySelector(".kpis"), Object.entries(d.kpis).map(([t, n]) => [n, t]));
    sugerencias(cuerpo.querySelector(".r-sug"));
    botonesCliente(cuerpo.querySelector(".f-cli"), d.clientes, f.cli, (v) => { f.cli = v; pintarTabla(); });
    const comision = () => { cuerpo.querySelector(".f-com").innerHTML = opc("Comisión", "comision", opcionesComision(), "Toda comisión"); };
    comision();
    escucharFiltros(cuerpo, f, (k) => {
      if (k === "camara") { f.comision = ""; comision(); }
      pintarTabla();
    });
    const live = cuerpo.querySelector(".r-live");
    if (live) live.onclick = async () => {
      live.disabled = true;
      const res = cuerpo.querySelector(".r-res");
      res.innerHTML = `<p class="nota pensando">Consultando la API del Congreso, unos 30 segundos.</p>`;
      try {
        const r = await App.pedir("live_pe");
        res.innerHTML = r.error_api ? `<p class="nota">${esc(r.error_api)}</p>` : r.nuevos.length
          ? `<p class="nota">${r.nuevos.length} proyectos nuevos en la API. La próxima sincronización los suma.</p>${r.nuevos.slice(0, 20).map((n) => `<div class="ag">${esc(n.PL ?? n.pl ?? n.titulo ?? JSON.stringify(n))}</div>`).join("")}`
          : `<p class="nota">Al día. API y base tienen ${miles(r.total_api)} proyectos.</p>`;
      } catch (e) { res.innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
      live.disabled = false;
    };
    pintarTabla();
  }

  return {
    titulo: pe ? "Proyectos de ley de Perú" : "Proyectos de ley de Ecuador",
    sub: pe ? "Congreso de la República, 2026 a 2031, bicameral" : "Asamblea Nacional, 2025 a 2029", seccion: nom,
    async abrir(cuerpo) {
      raiz = cuerpo;
      cuerpo.innerHTML = espera();
      d = await App.seccion(nom);
      if (App.ruta === nom) abrirVista(cuerpo);
    },
    nuevos(datos) { d = datos; if (raiz?.isConnected) pintarTabla(); },
  };
}
VISTAS.proyectos_pe = vistaProyectos("PE");
VISTAS.proyectos_ec = vistaProyectos("EC");
