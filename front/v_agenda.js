// Agenda parlamentaria de Peru y Ecuador.
function vistaAgenda(pais) {
  const nom = `agenda_${pais.toLowerCase()}`;
  const pe = pais === "PE";
  let d, raiz, vivos = [], reloj;
  const hoy = () => new Date().toISOString().slice(0, 10);
  const dias = (n) => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);
  const s = () => App.f(nom, { tab: "agenda", ini: pe ? "" : dias(-14), fin: dias(30), camara: "", comision: "", tipo: "", con_pls: "", orden: ["fecha", -1],
                               com_v: "", cli: "", semana: 0, vista: "Senado", plq: "" });

  function pestanasAgenda() {
    return pe ? [["agenda", "Agenda"], ["comision", "Por comisión"], ["mesas", "Mesas técnicas"], ["trans", "Transcripciones"], ["segui", "Seguimiento"]]
      : [["agenda", "Agenda"], ["comision", "Por comisión"], ["trans", "Transcripciones"]];
  }

  function sesionesFiltradas() {
    const f = s();
    return d.sesiones.filter((x) => (!f.ini || x.fecha >= f.ini) && (!f.fin || x.fecha <= f.fin) && (!f.camara || x.camara === f.camara) && (!f.comision || x.comision === f.comision)
      && (!f.tipo || x.tipo === f.tipo) && (f.con_pls !== "Solo con proyectos" || x.n_pls > 0) && (f.con_pls !== "Sin proyectos" || x.n_pls === 0));
  }

  function opcionesComision() {
    const f = s();
    return unicos(d.sesiones.filter((x) => !f.camara || x.camara === f.camara).map((x) => x.comision));
  }

  function tabAgenda(caja) {
    const f = s();
    const opc = (t, k, ops, todos) => campoFiltro({ k, t, todos, ops }, f);
    caja.innerHTML = `<div class="barra filtros">
      ${pe ? opc("Cámara", "camara", unicos(d.sesiones.map((x) => x.camara)), "Toda cámara") : ""}<span class="f-com"></span>
      ${pe ? opc("Tipo", "tipo", unicos(d.sesiones.map((x) => x.tipo)), "Todo tipo") : ""}
      ${opc("Con proyectos", "con_pls", ["Solo con proyectos", "Sin proyectos"], "Con y sin proyectos")}
      ${campoFiltro({ k: "ini", t: "Desde", tipo: "fecha" }, f)}${campoFiltro({ k: "fin", t: "Hasta", tipo: "fecha" }, f)}</div>
      ${pe ? `<div class="barra"><input class="buscar r-plq" placeholder="¿En qué agendas apareció un PL? Escribe el número" aria-label="Buscar PL en agendas"><button type="button" class="btn r-plb">Buscar</button></div><div class="r-plres"></div>` : ""}
      <p class="r-cuenta nota"></p><div class="t-ag"></div>`;
    const com = () => { caja.querySelector(".f-com").innerHTML = opc("Comisión", "comision", opcionesComision(), "Toda comisión"); };
    com();
    escucharFiltros(caja.querySelector(".filtros"), f, (k) => { if (k === "camara") { f.comision = ""; com(); } pinta(); });
    const pinta = () => {
      App.recordar(nom);
      const filas = sesionesFiltradas();
      caja.querySelector(".r-cuenta").textContent = `${plural(filas.length, "sesión", "sesiones")} de ${miles(d.sesiones.length)}`;
      const cols = [{ k: "fecha", t: "Fecha", f: (x) => esc(fechaCorta(x.fecha)) }, { k: "hora", t: "Hora" }, ...(pe ? [{ k: "camara", t: "Cámara" }] : []), { k: "comision", t: "Comisión" },
        ...(pe ? [] : [{ k: "trans", t: "Transcripción", f: (x) => { const ts = transDe(x); return !ts.length ? "" : ts.some((t) => t.resumen) ? "Con resumen" : "Transcrita"; } }]),
        { k: "pls", t: "Proyectos en agenda" }, { k: "nombre", t: "Sesión", f: (x) => `<span class="corta">${esc(x.nombre)}</span>` }];
      const t = caja.querySelector(".t-ag");
      t.tope = PASO;
      tabla(t, { cols, filas, orden: f.orden, alOrdenar: (o) => { f.orden = o; pinta(); }, clic: pe ? detallePe : detalleEc, vacio: "Sin sesiones con estos filtros." });
    };
    const b = caja.querySelector(".r-plb");
    if (b) {
      const q = caja.querySelector(".r-plq");
      const buscar = async () => {
        const res = caja.querySelector(".r-plres");
        const num = parseInt(q.value, 10);
        if (Number.isNaN(num)) { res.innerHTML = `<p class="nota">Escribe solo el número, por ejemplo 1000.</p>`; return; }
        res.innerHTML = `<p class="nota">Buscando…</p>`;
        try {
          const filas = await App.pedir("pl_en_agendas", { num });
          if (!filas.length) { res.innerHTML = `<p class="nota">El PL ${num} no aparece en ninguna sesión registrada.</p>`; return; }
          res.innerHTML = `<p class="nota"><b>PL ${num}</b>, ${filas.length} apariciones. ${esc(filas[0]["Título del PL"])}</p><div class="t-res"></div>`;
          tabla(res.querySelector(".t-res"), { filas, cols: [{ k: "Fecha", t: "Fecha", f: (r) => esc(fechaCorta(r.Fecha)) }, { k: "Hora", t: "Hora" }, { k: "Comisión", t: "Comisión" }, { k: "Tipo", t: "Tipo" }, { k: "Estado sesión", t: "Estado" }, { k: "Contexto en agenda", t: "Contexto" }] });
        } catch (e) { res.innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
      };
      b.onclick = buscar;
      q.onkeydown = (e) => { if (e.key === "Enter") buscar(); };
    }
    pinta();
  }

  const transDe = (x) => d.transcripciones.filter((t) => t.clave === x.clave);

  async function detallePe(x) {
    const nombre = { pleno: "Agenda del Pleno", youtube: "Solo en YouTube" }[x.fuente] ?? `Sesión ${x.id}`;
    const det = App.detalle(`<div class="marcas"><span>${esc(nombre)}</span><span>${esc(fechaCorta(x.fecha))} ${esc(x.hora)}</span><span>${esc(x.estado)}</span></div>
      <h2>${esc(x.nombre)}</h2><p class="nota">${esc(x.comision)} (${esc(x.tipo)})</p>
      <div class="linea">${enlace(x.teams, "Teams", "btn")}${enlace(x.video, "Video", "btn")}</div>
      ${x.fuente === "youtube" ? `<p class="nota">El Congreso transmitió esta sesión pero no la cargó en su visor, así que no hay orden del día oficial. La transcripción está en la pestaña Transcripciones.</p>` : ""}
      <div class="d-extra"><p class="nota">Buscando la agenda…</p></div>`);
    if (x.fuente === "youtube") { det.querySelector(".d-extra").innerHTML = ""; return; }
    try {
      const r = await App.pedir("sesion_pe", { id: x.id, fuente: x.fuente });
      const caja = det.querySelector(".d-extra");
      if (!caja) return;
      caja.innerHTML = `${r.pls.length ? `<h3 class="sub-t">Proyectos en agenda (${r.pls.length})</h3>${r.pls.map((p) => {
        const n = web(p["Nº PL"]) ? decodeURIComponent((p["Nº PL"].match(/\?pl=([^#]+)/) ?? [])[1] ?? "PL") : p["Nº PL"];
        return `<div class="ag">${enlace(p["Nº PL"], n) || esc(n)}<small>${esc(p.Tema)}, ${esc(p.Estado)}, ${esc(p.Bancada)}</small><span class="corta">${esc(p["Título"])}</span></div>`; }).join("")}` : ""}
        ${r.puntos.length ? `<details><summary>Orden del día (${plural(r.puntos.length, "punto")})</summary>${r.puntos.map((p) => `<div class="ag"><b>Punto ${p.orden + 1}</b><pre>${esc((p.descripcion_texto || "Sin texto").slice(0, 3000))}</pre></div>`).join("")}</details>` : ""}`;
    } catch (e) { det.querySelector(".d-extra").innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
  }

  async function detalleEc(x) {
    const ts = transDe(x);
    const det = App.detalle(`<div class="marcas"><span>${esc(fechaCorta(x.fecha))} ${esc(x.hora)}</span><span>${esc(x.comision)}</span></div><h2>${esc(x.nombre)}</h2>
      <div class="d-extra"><p class="nota">Buscando la agenda…</p></div>
      <h3 class="sub-t">Qué pasó en la sesión</h3>
      ${ts.length ? ts.map((t) => `<button type="button" class="ses" data-t="${esc(t.video_id)}">${esc(t.resumen ? t.resumen.slice(0, 160) : t.titulo)}</button>`).join("") : `<p class="nota">Todavía no hay transcripción. Las comisiones se transcriben cuando termina la transmisión en Facebook.</p>`}`);
    det.onclick = (e) => { const b = e.target.closest("[data-t]"); if (b) abrirTrans(ts.find((t) => t.video_id === b.dataset.t)); };
    try {
      const r = await App.pedir("sesion_ec", { uid: x.uid });
      const caja = det.querySelector(".d-extra");
      if (!caja) return;
      caja.innerHTML = `${r.lugar ? `<p class="nota">${esc(r.lugar)}</p>` : ""}${r.descripcion?.trim() ? `<details open><summary>Orden del día</summary><pre>${esc(r.descripcion)}</pre></details>` : ""}
        <h3 class="sub-t">Proyectos identificados (${r.pls.length})</h3>
        ${r.pls.length ? r.pls.map((p) => { const u = p["Nº trámite"]; const n = String(u).split("#")[1] ?? u; return `<div class="ag">${enlace(u, n) || esc(n)}<span class="corta">${esc(Object.entries(p).filter(([k]) => k !== "Nº trámite").map(([, v]) => v).filter(Boolean).join(", "))}</span></div>`; }).join("")
          : `<p class="nota">No se identificaron proyectos específicos en esta sesión.</p>`}`;
    } catch (e) { det.querySelector(".d-extra").innerHTML = `<p class="nota">${esc(e.message)}</p>`; }
  }

  function tabComision(caja) {
    const f = s();
    if (!d.por_comision.length) { caja.innerHTML = `<div class="vacio">No hay proyectos en agenda en el rango.</div>`; return; }
    const res = new Map();
    d.por_comision.forEach((r) => res.set(r.Comisión, (res.get(r.Comisión) ?? new Set()).add(r.PL)));
    const coms = [...res.entries()].sort((a, b) => b[1].size - a[1].size);
    caja.innerHTML = `<p class="nota">Proyectos referenciados en agendas. "Sesiones" cuenta en cuántas apareció cada uno.</p>
      <div class="barra filtros"><div class="f-cli"></div>${campoFiltro({ k: "com_v", t: "Comisión", todos: "Todas las comisiones", ops: coms.map(([c, p]) => [c, `${c}, ${p.size}`]) }, f)}</div>
      <p class="r-cuenta nota"></p><div class="t-com"></div>`;
    const pinta = () => {
      App.recordar(nom);
      const temas = f.cli ? d.temas_cliente[f.cli] ?? [] : null;
      const mat = f.cli ? d.matriz[f.cli] ?? [] : [];
      const filas = d.por_comision.filter((r) => (!f.com_v || r.Comisión === f.com_v) && (!f.cli || temas.includes(r.Tema) || mat.includes(String(r.PL))));
      const enMat = filas.filter((r) => mat.includes(String(r.PL))).length;
      caja.querySelector(".r-cuenta").textContent = `${plural(filas.length, "proyecto")} en agenda${enMat ? `, ${enMat} en la matriz de seguimiento` : ""}`;
      const url = pe ? "Nº PL" : "Nº trámite";
      tabla(caja.querySelector(".t-com"), { filas, clic: (r) => {
        const u = pe ? r["Nº PL"] : String(r["Nº trámite"]).split("#")[0];
        const it = item(`PL ${r.PL}: ${r.Título}`, u, `En agenda de ${r.Comisión} - ${r["Estado del PL"]}`, pais, null, null, "pl");
        const det = App.detalle(`<div class="marcas"><span>${esc(r.Comisión)}</span><span>${esc(r.Tema)}</span><span>${esc(r["Estado del PL"])}</span></div><h2>${esc(r.Título)}</h2>
          <p class="nota">PL ${esc(r.PL)}. ${r.Sesiones} sesiones, de ${esc(fechaCorta(r.Primera))} a ${esc(fechaCorta(r.Última))}.</p>
          <div class="acciones">${enlace(u, "Abrir el proyecto", "btn pri")}${bloqueArmar([it], f.cli, null, d.clientes)}</div>`);
        conectarArmar(det, [it]);
      }, cols: [{ k: "Comisión", t: "Comisión" }, { k: "PL", t: "PL", f: (r) => enlace(r[url], r.PL) || esc(r.PL) }, { k: "Tema", t: "Tema" }, { k: "Estado del PL", t: "Estado" },
        { k: "Título", t: "Título", f: (r) => `<span class="corta">${esc(r.Título)}</span>` }, { k: "Sesiones", t: "Sesiones" }, { k: "Primera", t: "1.ª vez", f: (r) => esc(fechaCorta(r.Primera)) }, { k: "Última", t: "Última", f: (r) => esc(fechaCorta(r.Última)) }] });
    };
    escucharFiltros(caja, f, pinta);
    botonesCliente(caja.querySelector(".f-cli"), d.clientes, f.cli, (v) => { f.cli = v; pinta(); });
    pinta();
  }

  function tabMesas(caja) {
    caja.innerHTML = `<p class="nota">Convocatorias de congresistas y comisiones: mesas técnicas, ceremonias y sesiones descentralizadas que no aparecen en el visor de sesiones.</p><div class="t-mes"></div>`;
    tabla(caja.querySelector(".t-mes"), { filas: d.mesas, vacio: "Sin mesas o eventos registrados todavía.", cols: [{ k: "Fecha", t: "Fecha" }, { k: "Hora", t: "Hora" }, { k: "Tipo", t: "Tipo" },
      { k: "Tema", t: "Tema", f: (r) => enlace(r.Enlace, r.Tema) || esc(r.Tema) }, { k: "Organiza", t: "Organiza" }, { k: "Bancada", t: "Bancada" }, { k: "Comisión", t: "Comisión" }] });
  }

  function urlDe(t) { return t.url ?? (String(t.video_id).startsWith("fb_") ? null : `https://www.youtube.com/watch?v=${t.video_id}`); }

  function abrirTrans(t) {
    const det = App.detalle(fichaTranscripcion(t, urlDe(t)));
    conectarTranscripcion(det, t);
  }

  function tabTrans(caja) {
    const f = s();
    const vivosPais = vivos.filter((v) => v.pais === pais);
    const zonaVivos = vivosPais.length ? `<h2 class="grupo-t">En vivo ahora</h2>${vivosPais.map((v) => `<div class="ag"><span class="punto"></span>${enlace(v.url, v.tipo)} ${esc(v.titulo.slice(0, 90))}
      <small>${v.minutos != null ? `Transcribiéndose, unos ${v.minutos} minutos cubiertos.` : "Una sesión recién empezada tarda unos 20 a 25 minutos en verse aquí."}</small>${v.resumen?.resumen ? `<p>${esc(v.resumen.resumen)}</p>` : ""}</div>`).join("")}` : "";
    if (!pe) {
      caja.innerHTML = `${zonaVivos}<p class="nota">Pleno por YouTube, también en vivo. Comisiones por Facebook, cuando la sesión termina.</p><div class="lista-t"></div>`;
      caja.querySelector(".lista-t").innerHTML = d.transcripciones.slice(0, 40).map((t, i) => `<button type="button" class="ses" data-tr="${i}">${esc(fechaCorta(t.fecha))}, ${esc(t.tipo.split(":").pop().replace("(EC)", "").trim())}<small>${esc(t.titulo.slice(0, 90))}</small></button>`).join("") || `<div class="vacio">Todavía no hay sesiones transcritas.</div>`;
      caja.onclick = (e) => { const b = e.target.closest("[data-tr]"); if (b) abrirTrans(d.transcripciones[b.dataset.tr]); };
      return;
    }
    caja.innerHTML = `${zonaVivos}<h2 class="grupo-t">Por semana</h2>
      <div class="barra"><button type="button" class="btn s-ant">Anterior</button><b class="s-et"></b><button type="button" class="btn s-sig">Siguiente</button><button type="button" class="btn s-hoy">Esta semana</button><span class="f-v"></span></div>
      <div class="t-sem"></div><details class="prev"><summary>Sesiones previas, por fecha (${d.transcripciones.length})</summary><div class="l-prev"></div></details>`;
    const queP = (t) => t.resumen || (t.extracto ? `${t.extracto}…` : "Resumen pendiente de generar.");
    const pinta = () => {
      App.recordar(nom);
      const lunesHoy = new Date(); lunesHoy.setDate(lunesHoy.getDate() - ((lunesHoy.getDay() + 6) % 7));
      const lunes = new Date(lunesHoy); lunes.setDate(lunes.getDate() + 7 * f.semana);
      const dom = new Date(lunes); dom.setDate(dom.getDate() + 6);
      const iso = (x) => x.toISOString().slice(0, 10);
      caja.querySelector(".s-et").textContent = `${fechaCorta(iso(lunes)).slice(0, 5)} al ${fechaCorta(iso(dom)).slice(0, 5)}`;
      caja.querySelector(".s-hoy").hidden = f.semana === 0;
      const sem = d.transcripciones.filter((t) => t.fecha >= iso(lunes) && t.fecha <= iso(dom));
      const filas = [];
      if (f.vista === "Plenos y conjuntas") {
        sem.filter((t) => ["Congreso", "Conjunta"].includes(t.camara)).forEach((t) => filas.push({ c: (t.tipo.startsWith("Pleno:") ? "Pleno " : "") + t.tipo.split(":").pop().trim(), q: queP(t), t }));
      } else {
        const cat = f.vista === "Senado" ? d.senado : d.diputados;
        const cam = sem.filter((t) => t.camara === f.vista);
        const tipos = new Set();
        cat.forEach(([n, tipo]) => {
          tipos.add(tipo);
          const hay = cam.filter((t) => t.tipo === tipo);
          if (hay.length) hay.forEach((t) => filas.push({ c: n, q: queP(t), t })); else filas.push({ c: n, q: "No sesionó esta semana." });
        });
        cam.filter((t) => !tipos.has(t.tipo)).forEach((t) => filas.push({ c: t.tipo.split(":").pop().trim(), q: queP(t), t }));
      }
      tabla(caja.querySelector(".t-sem"), { filas, cols: [{ k: "c", t: "Comisión" }, { k: "q", t: "Qué pasó", f: (r) => (r.t ? `<span class="corta">${esc(r.q)}</span>` : `<span class="nota">${esc(r.q)}</span>`) }],
        clic: (r) => { if (r.t) abrirTrans(r.t); }, vacio: "Nada de Plenos conjuntos o comisiones bicamerales esta semana." });
    };
    segmentado(caja.querySelector(".f-v"), ["Senado", "Diputados", "Plenos y conjuntas"], f.vista, (t) => { f.vista = t; pinta(); });
    caja.querySelector(".s-ant").onclick = () => { f.semana -= 1; pinta(); };
    caja.querySelector(".s-sig").onclick = () => { f.semana += 1; pinta(); };
    caja.querySelector(".s-hoy").onclick = () => { f.semana = 0; pinta(); };
    const prev = new Map();
    d.transcripciones.forEach((t) => { const k = t.fecha || "Sin fecha"; if (!prev.has(k)) prev.set(k, []); prev.get(k).push(t); });
    caja.querySelector(".l-prev").innerHTML = [...prev].map(([k, g]) => `<h3 class="sub-t">${esc(fechaCorta(k) || k)} (${g.length})</h3>${g.map((t) => `<button type="button" class="ses" data-vid="${esc(t.video_id)}">[${esc(t.camara)}] ${esc(t.tipo)}<small>${esc(t.titulo.slice(0, 90))}</small></button>`).join("")}`).join("");
    caja.querySelector(".l-prev").onclick = (e) => { const b = e.target.closest("[data-vid]"); if (b) abrirTrans(d.transcripciones.find((t) => t.video_id === b.dataset.vid)); };
    pinta();
  }

  function tabSegui(caja) {
    const grupos = new Map();
    d.comisiones.forEach((c) => { const k = c.camara || "Sin cámara"; if (!grupos.has(k)) grupos.set(k, new Set()); grupos.get(k).add(c.nombre); });
    const marcadas = new Set(d.seguidas);
    caja.innerHTML = `<p class="nota">Marca las comisiones prioritarias. Se guarda para ti, no por cliente, y se usa en las alertas.</p>
      ${[...grupos].sort().map(([c, n]) => `<h3 class="sub-t">${esc(c)}</h3>${[...n].sort().map((x) => `<label class="check"><input type="checkbox" value="${esc(x)}"${marcadas.has(x) ? " checked" : ""}>${esc(x)}</label>`).join("")}`).join("")}
      <div class="acciones"><button type="button" class="btn pri r-guardar">Guardar</button></div>`;
    caja.querySelector(".r-guardar").onclick = async () => {
      const comisiones = [...caja.querySelectorAll("input:checked")].map((i) => i.value);
      try { await App.pedir("seguir", { comisiones }); d.seguidas = comisiones; App.aviso(`Guardado, ${plural(comisiones.length, "comisión", "comisiones")} prioritarias`); } catch (e) { App.fallo(e); }
    };
  }

  function pintarTab() {
    const f = s();
    App.recordar(nom);
    pestanas(raiz.querySelector(".tabs"), pestanasAgenda(), f.tab, (t) => { f.tab = t; pintarTab(); });
    const caja = raiz.querySelector(".vista");
    caja.onclick = caja.oninput = null;
    ({ agenda: tabAgenda, comision: tabComision, mesas: tabMesas, trans: tabTrans, segui: tabSegui }[f.tab] ?? tabAgenda)(caja);
    if (!quieto()) caja.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140 });
  }

  function banda() {
    const c = raiz.querySelector(".vivos");
    if (!c) return;
    const lista = vivos.filter((v) => v.pais === pais);
    c.hidden = !lista.length;
    c.innerHTML = lista.map((v) => `<div><span class="punto"></span>En vivo: ${enlace(v.url, v.tipo)} ${esc(v.titulo.slice(0, 90))}</div>`).join("");
  }

  async function mirarVivos() {
    try { vivos = (await App.pedir("seccion", { nombre: "vivos" })).datos ?? []; banda(); } catch { /* sin aviso: es un extra */ }
  }

  return {
    titulo: pe ? "Agenda parlamentaria de Perú" : "Agenda parlamentaria de Ecuador",
    sub: pe ? "Senado, Cámara de Diputados y Pleno" : "Comisiones y Pleno de la Asamblea Nacional", seccion: nom,
    async abrir(cuerpo) {
      raiz = cuerpo;
      cuerpo.innerHTML = espera();
      d = await App.seccion(nom);
      if (App.ruta !== nom) return;
      cuerpo.innerHTML = `<div class="vivos" hidden></div><div class="kpis"></div><div class="tabs" role="tablist"></div><div class="vista"></div>
        ${pe ? `<details class="segui"><summary>Cobertura y límites de esta vista</summary><p class="nota">Muestra el Congreso bicameral vigente desde el 27 de julio de 2026. Incluye comisiones del Senado, de Diputados y el Pleno. La Comisión Permanente, la Subcomisión de Acusaciones Constitucionales y las investigadoras no se publican por las API disponibles. Las comisiones con el mismo nombre en ambas cámaras pueden quedar sin clasificar.</p></details>` : ""}`;
      kpis(cuerpo.querySelector(".kpis"), Object.entries(d.kpis).map(([t, n]) => [n, t]));
      pintarTab();
      mirarVivos();
      clearInterval(reloj);
      reloj = setInterval(() => { if (raiz.isConnected) mirarVivos(); else clearInterval(reloj); }, 90000);
    },
    nuevos(datos) { d = datos; },
  };
}
VISTAS.agenda_pe = vistaAgenda("PE");
VISTAS.agenda_ec = vistaAgenda("EC");
