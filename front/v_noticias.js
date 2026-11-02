// Noticias y TV de un pais. Las reglas de cada filtro son las de noticias/pagina.py;
// por cliente, el servidor ya mando que noticia le corresponde a cada uno.
function vistaNoticias(pais) {
  const nom = `noticias_${pais.toLowerCase()}`;
  let d, raiz, lista = [], tambien = new Map(), combinar = new Map(), cliCombina = "";
  const s = () => App.f(nom, { tab: "noticias", ven: "Hoy", cli: "", tema: "", q: "", cat: "", fuente: "", norma: "Sin normativa",
                               relevante: true, alerta: false, afin: true });
  const nivelDe = (n, c) => n.nivel?.[c];

  function filtrar() {
    const f = s();
    const q = (f.q ?? "").toLowerCase();
    const corte = d.cortes[f.ven];
    let filas = d.filas.filter((n) => n.fecha >= corte && !App.fuera.has(n.id)
      && (!f.cat || n.cat === f.cat) && (!f.fuente || n.fuente === f.fuente) && (!f.cli || n.para.includes(f.cli))
      && (!q || `${n.titulo} ${n.resumen}`.toLowerCase().includes(q)));
    if (f.tema) {
      filas = filas.filter((n) => n.temas.includes(f.tema) || f.tema in n.sector)
        .sort((a, b) => (b.sector[f.tema] ?? -1) - (a.sector[f.tema] ?? -1));
    }
    if (f.norma === "Sin normativa") filas = filas.filter((n) => !n.norma);
    if (f.norma === "Solo normativa") filas = filas.filter((n) => n.norma);
    // Coyuntura politica pasa siempre y lo que el cerebro aun no leyo tambien
    const pesos = (n) => Object.entries(n.af).filter(([c]) => !f.cli || c === f.cli).map(([, v]) => v);
    const relevante = (n) => { const p = pesos(n); return !p.length || Math.max(...p) >= d.umbral || n.temas.includes("Coyuntura política"); };
    const ocultas = filas.filter((n) => !relevante(n)).length;
    if (f.relevante) filas = filas.filter(relevante);
    const merece = (n) => Object.keys(n.interesa).some((c) => !f.cli || c === f.cli);
    const conAlerta = filas.filter(merece).length;
    if (f.alerta) filas = filas.filter(merece);
    const porAfin = !!(f.cli && f.afin);
    if (porAfin) filas = [...filas].sort((a, b) => (b.af[f.cli] ?? -1) - (a.af[f.cli] ?? -1));
    // Mismo hecho en varios portales: una tarjeta con "Tambien en"
    tambien = new Map();
    const principal = new Map();
    for (const n of filas) {
      if (!principal.has(n.grupo)) { principal.set(n.grupo, n); tambien.set(n.id, []); } else tambien.get(principal.get(n.grupo).id).push(n);
    }
    lista = [...principal.values()];
    return { ocultas, conAlerta, plana: !!(f.tema || f.cat || porAfin) };
  }

  function tarjeta(n) {
    const f = s();
    const otros = tambien.get(n.id) ?? [];
    const clis = Object.keys(n.interesa).filter((c) => !f.cli || c === f.cli);
    const nivel = f.cli ? nivelDe(n, f.cli) : null;
    const soloSentido = f.tema && !n.temas.includes(f.tema);
    return `<article class="fila ${n.norma ? "norma" : "noticia"}" data-id="${n.id}" tabindex="0">
      <div class="marcas"><span>${esc(n.fuente)}</span><span>${esc(fechaCorta(n.fecha))}</span>
      ${n.norma ? "<span>Normativa</span>" : ""}${n.temas.map((t) => `<span>${esc(t)}</span>`).join("")}
      ${nivel ? `<span class="cli">Relevancia ${esc(nivel.toLowerCase())}</span>` : ""}
      ${soloSentido ? `<span>Del sector por su contenido</span>` : ""}
      ${enlace(n.url, "Abrir fuente", "fuente")}</div>
      <h3>${esc(n.titulo)}</h3>
      ${n.resumen ? `<p>${esc(n.resumen.slice(0, 240))}</p>` : ""}
      ${clis.map((c) => `<p><b>${esc(App.nombre(c))}.</b> ${esc(n.interesa[c])}</p>`).join("")}
      ${n.pl ? `<small>Posible relación con el proyecto: ${esc(n.pl.slice(0, 90))}</small>` : ""}
      ${otros.length ? `<small>También en ${otros.map((o) => enlace(o.url, o.fuente)).join(", ")}</small>` : ""}
      <label class="check sumar"><input type="checkbox" data-sumar="${n.id}"${combinar.has(n.id) ? " checked" : ""}>Combinar</label></article>`;
  }

  function dibujarLista(animar) {
    const r = filtrar();
    const f = s();
    App.recordar(nom, ["q"]);
    const caja = raiz.querySelector(".lista");
    raiz.querySelector(".r-rel").textContent = f.cli ? `Solo lo relevante para ${App.nombre(f.cli)} (${r.ocultas} ocultas)` : `Solo lo relevante para tus clientes (${r.ocultas} ocultas)`;
    raiz.querySelector(".r-ale").textContent = `Solo las que merecen alerta (${r.conAlerta})`;
    raiz.querySelector(".r-afi").hidden = !f.cli;
    raiz.querySelector(".r-cuenta").textContent = `${plural(lista.length, "noticia")}, ${f.ven.toLowerCase()}`;
    if (!lista.length) { caja.innerHTML = `<div class="vacio">Sin noticias con esos filtros. Prueba ampliar el periodo, cambiar el tema o limpiar la búsqueda.</div>`; return; }
    if (r.plana) caja.innerHTML = lista.slice(0, 150).map(tarjeta).join("");
    else {
      const grupos = new Map(d.temas.map((t) => [t, []]));
      const otros = [];
      for (const n of lista) {
        const t = n.temas.filter((x) => grupos.has(x));
        if (t.length) t.forEach((x) => grupos.get(x).push(n)); else otros.push(n);
      }
      const bloque = (t, g, max) => (g.length ? `<h2 class="grupo-t">${esc(t)} <span>${g.length}</span></h2>${g.slice(0, max).map(tarjeta).join("")}` : "");
      caja.innerHTML = [...grupos].map(([t, g]) => bloque(t, g, 30)).join("") + bloque("Otros", otros, 20);
    }
    if (animar) entrar(caja.querySelectorAll(".fila"));
    dibujarCombinar();
  }

  function dibujarCombinar() {
    const caja = raiz.querySelector(".combina");
    if (!combinar.size) { caja.hidden = true; return; }
    caja.hidden = false;
    const previa = caja.querySelector('input[name="princ"]:checked')?.value;
    caja.innerHTML = `<h2>Combinar en una sola alerta (${combinar.size})</h2>
      <p class="nota">La alerta cita solo la fuente principal.</p>
      ${[...combinar.values()].map((n, i) => `<label class="check"><input type="radio" name="princ" value="${n.id}"${String(n.id) === previa || (!previa && !i) ? " checked" : ""}>${esc(n.titulo.slice(0, 70))}, ${esc(n.fuente)}</label>`).join("")}
      <div class="c-cli"></div><button type="button" class="btn pri c-armar">Armar una alerta con estas</button>`;
    botonesCliente(caja.querySelector(".c-cli"), d.clientes, cliCombina, (v) => { cliCombina = v; }, false);
  }

  function detalle(n) {
    const f = s();
    const otros = tambien.get(n.id) ?? [];
    const items = [n, ...otros].map((x) => item(x.titulo, x.url, x.resumen || null, pais, x.fuente, x.fecha));
    const elegido = f.cli || Object.keys(n.interesa)[0] || "";
    const det = App.detalle(`<div class="marcas"><span>${esc(n.fuente)}</span><span>${esc(fechaCorta(n.fecha))}</span>${n.temas.map((t) => `<span>${esc(t)}</span>`).join("")}</div>
      <h2>${esc(n.titulo)}</h2>
      ${Object.entries(n.interesa).map(([c, p]) => `<div class="por"><b>${esc(App.nombre(c))}</b>${esc(p)}</div>`).join("")}
      ${n.resumen ? `<p>${esc(n.resumen.slice(0, 900))}</p>` : ""}
      <div class="acciones">${enlace(n.url, "Abrir la fuente", "btn pri")}${bloqueArmar(items, elegido, null, d.clientes)}
      <button type="button" class="btn des d-descartar">Descartar esta noticia</button></div>`);
    conectarArmar(det, items, (c) => n.interesa[c] ?? null);
    det.querySelector(".d-descartar").onclick = () => descartar(n.id, n.titulo, () => dibujarLista(false));
  }

  function abrirNoticias(caja) {
    const f = s();
    caja.innerHTML = `<div class="kpis"></div>
      <div class="barra"><div class="f-cli"></div></div>
      <div class="barra filtros">${campoFiltro({ k: "tema", t: "Sector o tema", todos: "Todos los temas", ops: d.temas }, f)}
        ${campoFiltro({ k: "q", t: "Buscar en título o resumen (tecla /)", tipo: "texto" }, f)}
        <details class="mas-f"><summary>Más filtros</summary><div class="barra">
          ${campoFiltro({ k: "cat", t: "Categoría de fuente", todos: "Toda categoría de fuente", ops: d.categorias }, f)}
          ${campoFiltro({ k: "fuente", t: "Fuente", todos: "Todas las fuentes", ops: d.fuentes }, f)}</div></details></div>
      <div class="barra"><span class="f-norma"></span>
        <label class="check"><input type="checkbox" data-f="relevante"${f.relevante ? " checked" : ""}><span class="r-rel"></span></label>
        <label class="check"><input type="checkbox" data-f="alerta"${f.alerta ? " checked" : ""}><span class="r-ale"></span></label>
        <label class="check r-afi"><input type="checkbox" data-f="afin"${f.afin ? " checked" : ""}>Ordenar por afinidad</label></div>
      <p class="r-cuenta nota"></p><div class="lista"></div><div class="combina" hidden></div>
      ${d.seguimiento?.length ? `<details class="segui"><summary>Seguimiento de proyectos de interés</summary><div class="t-seg"></div></details>` : ""}`;
    const k = d.kpis;
    kpis(caja.querySelector(".kpis"), Object.entries(k).map(([t, n]) => [n, t]));
    botonesCliente(caja.querySelector(".f-cli"), d.clientes, f.cli, (v) => { f.cli = v; dibujarLista(true); });
    segmentado(caja.querySelector(".f-norma"), ["Sin normativa", "Todas", "Solo normativa"], f.norma, (t) => { f.norma = t; dibujarLista(true); });
    escucharFiltros(caja, f, (k) => dibujarLista(k !== "q"));
    caja.onclick = (e) => {
      const t = e.target;
      if (t.closest("a") || t.closest(".sumar")) return;
      if (t.closest(".c-armar")) return armarCombinadas();
      const fi = t.closest(".fila");
      if (fi) detalle(d.filas.find((n) => n.id === Number(fi.dataset.id)));
    };
    caja.onchange = (e) => {
      const id = e.target.dataset?.sumar;
      if (!id) return;
      const n = d.filas.find((x) => x.id === Number(id));
      if (e.target.checked) combinar.set(n.id, n); else combinar.delete(n.id);
      dibujarCombinar();
    };
    if (d.seguimiento?.length) {
      tabla(caja.querySelector(".t-seg"), { filas: d.seguimiento, cols: [
        { k: "Cliente", t: "Cliente" }, { k: "PL de interés", t: "Proyecto de interés" },
        { k: "Última noticia", t: "Última noticia", f: (r) => enlace(r.Enlace, r["Última noticia"]) || esc(r["Última noticia"]) },
        { k: "Fecha", t: "Fecha", f: (r) => esc(fechaCorta(r.Fecha)) }, { k: "N° noticias", t: "Noticias" }] });
    }
    dibujarLista(true);
    App.ajustar();
  }

  function armarCombinadas() {
    const caja = raiz.querySelector(".combina");
    const cli = cliCombina;
    if (!cli) return App.aviso("Elige el cliente");
    const princ = Number(caja.querySelector('input[name="princ"]:checked').value);
    const orden = [combinar.get(princ), ...[...combinar.values()].filter((n) => n.id !== princ)];
    App.pedir("combinadas", { ids: orden.map((n) => n.id) }).catch((e) => console.warn("[combinar]", e.message));  // nunca frena la alerta
    combinar = new Map();
    App.armar(orden.map((n) => item(n.titulo, n.url, n.resumen || null, pais, n.fuente, n.fecha)), cli);
  }

  // ---- TV y entrevistas
  async function abrirTV(caja) {
    const f = App.f(`${nom}_tv`, { dias: "Última semana", q: "", sel: "" });
    caja.innerHTML = espera(4);
    const tv = await App.seccion(`tv_${pais.toLowerCase()}`);
    if (s().tab !== "tv" || App.ruta !== nom) return;
    const dias = { "Últimos 3 días": 3, "Última semana": 7, "Últimas 2 semanas": 14 };
    const etiquetas = unicos([...tv.videos.map((v) => v.autoridad), ...tv.menciones.flatMap((m) => m.terminos.split(", "))]);
    caja.innerHTML = `<p class="nota">Entrevistas de las autoridades que seguimos en TV y radio, y lo que se dijo en programas de noticias sobre ellas y los temas de los clientes.</p>
      <div class="barra filtros"><span class="f-dias"></span>${campoFiltro({ k: "sel", t: "Autoridad o tema", todos: "Toda autoridad o tema", ops: etiquetas }, f)}
      ${campoFiltro({ k: "q", t: "Buscar en título, resumen o fragmento", tipo: "texto" }, f)}</div>
      <div class="kpis"></div><div class="tv"></div>`;
    const pinta = () => {
      const corte = new Date(Date.now() - dias[f.dias] * 864e5).toISOString().slice(0, 10);
      const q = (f.q ?? "").toLowerCase();
      const v = tv.videos.filter((x) => x.fecha >= corte && (!f.sel || x.autoridad === f.sel) && (!q || `${x.titulo} ${x.resumen ?? ""}`.toLowerCase().includes(q)));
      const m = tv.menciones.filter((x) => x.fecha >= corte && (!f.sel || x.terminos.includes(f.sel)) && (!q || `${x.titulo} ${x.fragmento}`.toLowerCase().includes(q))).slice(0, 250);
      kpis(caja.querySelector(".kpis"), [[v.length, "Entrevistas"], [v.filter((x) => x.transcrito).length, "Transcritas"], [m.length, "Menciones en TV"]]);
      const hist = new Map();
      m.forEach((x) => { if (!hist.has(x.historia)) hist.set(x.historia, []); hist.get(x.historia).push(x); });
      const zona = caja.querySelector(".tv");
      zona.innerHTML = `<h2 class="grupo-t">Entrevistas de autoridades <span>${v.length}</span></h2>
        ${v.slice(0, 60).map((x, i) => `<article class="fila noticia" data-v="${i}" tabindex="0"><div class="marcas"><span>${esc(x.canal)}</span><span>${esc(fechaCorta(x.fecha))}</span><span>${x.min} min</span><span class="cli">${esc(x.autoridad)}</span>${enlace(`https://www.youtube.com/watch?v=${x.video_id}`, "Ver video", "fuente")}</div>
          <h3>${esc(x.titulo)}</h3>${x.resumen ? `<p>${esc(x.resumen)}</p>` : x.transcrito ? `<small>Transcrita. El resumen se genera en la próxima hora.</small>` : x.pedido ? `<small>Transcribiendo, 10 a 40 minutos.</small>` : ""}</article>`).join("") || `<div class="vacio">Sin entrevistas con esos filtros.</div>`}
        <h2 class="grupo-t">Menciones en programas de TV <span>${hist.size} historias, ${m.length} menciones</span></h2>
        ${[...hist.values()].slice(0, 80).map((g, i) => { const r = g[0]; const fr = r.fragmento.length > 700 ? `${r.fragmento.slice(0, 700)}…` : r.fragmento;
          return `<article class="fila noticia" data-h="${i}" tabindex="0"><div class="marcas"><span>${esc(r.canal)}</span><span>${esc(r.donde)}</span><span>${esc(fechaCorta(r.fecha))}</span>${unicos(g.flatMap((o) => o.terminos.split(", "))).map((t) => `<span class="cli">${esc(t)}</span>`).join("")}${enlace(r.url, "Ver momento", "fuente")}</div>
          <h3>${esc(r.titulo)}</h3><p>«${esc(fr)}»</p>${g.length > 1 ? `<small>También en ${unicos(g.slice(1).map((o) => `${o.canal} (${o.donde})`)).slice(0, 8).map(esc).join(", ")}</small>` : ""}</article>`; }).join("") || `<div class="vacio">Sin menciones con esos filtros.</div>`}`;
      zona.onclick = (e) => {
        if (e.target.closest("a")) return;
        const a = e.target.closest("[data-v]"), b = e.target.closest("[data-h]");
        if (a) detalleVideo(v[a.dataset.v]);
        if (b) detalleMencion([...hist.values()][b.dataset.h]);
      };
    };
    segmentado(caja.querySelector(".f-dias"), Object.keys(dias), f.dias, (t) => { f.dias = t; pinta(); });
    escucharFiltros(caja, f, pinta);
    pinta();
  }

  function detalleVideo(x) {
    const url = `https://www.youtube.com/watch?v=${x.video_id}`;
    const it = item(x.titulo, url, x.resumen, pais, x.canal, x.fecha, "video");
    const det = App.detalle(`<div class="marcas"><span>${esc(x.canal)}</span><span>${esc(x.autoridad)}</span><span>${x.min} min</span></div><h2>${esc(x.titulo)}</h2>
      ${x.resumen ? `<p>${esc(x.resumen)}</p>` : ""}${x.ideas.length ? `<ul>${x.ideas.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
      <div class="acciones">${enlace(url, "Ver el video", "btn pri")}${bloqueArmar([it], "", null, d.clientes)}
      ${x.transcrito ? `<button type="button" class="btn d-texto">Ver transcripción</button><div class="texto" hidden></div>`
        : x.pedido ? `<p class="nota">Transcribiendo, 10 a 40 minutos.</p>` : `<button type="button" class="btn d-tx">Transcribir y resumir</button>`}</div>`);
    conectarArmar(det, [it]);
    const tx = det.querySelector(".d-texto");
    if (tx) tx.onclick = () => verTexto(det, x.video_id, x.titulo);
    const pedir = det.querySelector(".d-tx");
    if (pedir) pedir.onclick = async () => {
      pedir.disabled = true;
      try {
        await App.pedir("transcribir", { video_id: x.video_id, autoridad: x.autoridad, pais, titulo: x.titulo });
        x.pedido = true;
        pedir.replaceWith(Object.assign(document.createElement("p"), { className: "nota", textContent: "Transcribiendo, 10 a 40 minutos." }));
      } catch (e) { pedir.disabled = false; App.fallo(e); }
    };
  }

  function detalleMencion(g) {
    const r = g[0];
    const it = item(r.titulo, r.url, r.fragmento, pais, r.canal, r.fecha, "video");
    const det = App.detalle(`<div class="marcas"><span>${esc(r.canal)}</span><span>${esc(r.donde)}</span></div><h2>${esc(r.titulo)}</h2><p>«${esc(r.fragmento)}»</p>
      <div class="acciones">${enlace(r.url, "Ver el momento", "btn pri")}${bloqueArmar([it], "", null, d.clientes)}
      ${r.transcrito ? `<button type="button" class="btn d-texto">Ver transcripción</button><div class="texto" hidden></div>` : ""}</div>`);
    conectarArmar(det, [it]);
    const tx = det.querySelector(".d-texto");
    if (tx) tx.onclick = () => verTexto(det, r.video_id, r.titulo);
  }

  function pintarTab() {
    const f = s();
    App.recordar(nom, ["q"]);
    pestanas(raiz.querySelector(".tabs"), [["noticias", "Noticias"], ["tv", "TV y entrevistas"]], f.tab, (t) => { f.tab = t; pintarTab(); });
    const ctrl = App.$(".ctrl");
    const caja = raiz.querySelector(".vista");
    caja.onclick = caja.onchange = caja.oninput = null;
    if (f.tab === "tv") { ctrl.innerHTML = ""; return abrirTV(caja).catch((e) => { caja.innerHTML = `<div class="aviso">${esc(e.message)}</div>`; }); }
    ctrl.innerHTML = '<div class="f-ven"></div>';
    segmentado(ctrl.querySelector(".f-ven"), Object.keys(d.cortes), f.ven, (t) => { f.ven = t; dibujarLista(true); });
    abrirNoticias(caja);
  }

  return {
    titulo: `Noticias de ${PAISES[pais]}`, sub: "Medios, instituciones, ministerios, reguladores y gremios", seccion: nom,
    async abrir(cuerpo) {
      raiz = cuerpo;
      cuerpo.innerHTML = espera();
      d = await App.seccion(nom);
      if (App.ruta !== nom) return;
      cuerpo.innerHTML = `<div class="tabs" role="tablist"></div><div class="vista"></div>`;
      pintarTab();
    },
    nuevos(datos) { d = datos; if (s().tab === "noticias" && raiz?.isConnected) dibujarLista(false); },
  };
}
VISTAS.noticias_pe = vistaNoticias("PE");
VISTAS.noticias_ec = vistaNoticias("EC");
