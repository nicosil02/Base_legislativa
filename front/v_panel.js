// Panel de monitoreo.
const TIPOS = { norma: "Norma", pl: "Proyecto", noticia: "Noticia" };

VISTAS.panel = (() => {
  const nom = "panel";
  let d, raiz, filas = [], universo = [], proyectos = [], agenda = [], sesiones = [], sel = null;
  const s = () => App.f(nom, { pais: "Todos", cli: "", ven: "Desde ayer 4 p. m.", tab: "alertas", tipo: "Todas", q: "", etapa: null, orden: ["cambio", -1],
                               bandeja: "Por revisar" });
  const igual = (a, b) => !!a && !!b && a.titulo === b.titulo && a.url === b.url;
  // Bandeja: cada alerta queda por revisar hasta que se alerta, se deja para despues o se descarta
  const clave = (a) => (a.id != null ? `n${a.id}` : `${a.tipo}:${a.url || a.titulo}`);
  const estado = (a) => App.bandeja[clave(a)]?.estado ?? (App.fuera.has(a.id) ? "descartar" : null);
  const CAJAS = { "Por revisar": (e) => !e, "Para después": (e) => e === "despues", Alertadas: (e) => e === "alertar", Interesantes: (e) => e === "interesante", Descartadas: (e) => e === "descartar" };

  function filtrar() {
    const f = s();
    const v = d.ventanas[f.ven];
    const paises = Object.keys(PAISES).filter((p) => !App.pais || p === App.pais);
    const slugs = f.cli ? [f.cli] : Object.keys(App.d.clientes);
    const cubre = new Set(slugs.flatMap((c) => App.d.clientes[c].paises));
    const q = (f.q ?? "").toLowerCase();
    const todas = v.alertas.filter((a) => paises.includes(a.pais)
      && (a.tipo === "norma" && !Object.keys(a.porque).length ? cubre.has(a.pais) : Object.keys(a.porque).some((c) => slugs.includes(c))));
    universo = todas;
    const caja = CAJAS[f.bandeja] ?? CAJAS["Por revisar"];
    filas = todas.filter((a) => caja(estado(a)) && (f.tipo === "Todas" || TIPOS[a.tipo] === f.tipo)
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
    const otras = a.otras.length ? `, también en ${a.otras.length > 3 ? `${a.otras.slice(0, 2).join(", ")} y ${a.otras.length - 2} más` : a.otras.join(", ").replace(/, ([^,]*)$/, " y $1")}` : "";
    return `<article class="fila ${a.tipo}${igual(sel, a) ? " activa" : ""}" data-i="${i}" tabindex="0">
      <div class="marcas"><span class="tipo">${TIPOS[a.tipo]}</span><span>${PAISES[a.pais] ?? esc(a.pais)}</span>${a.tema ? `<span>${esc(a.tema)}</span>` : ""}
      ${clientes.map((c) => `<span class="cli">${esc(App.nombre(c))}</span>`).join("")}
      <span class="acc">${enlaceIcono(a.url, "Abrir fuente")}${estado(a)
        ? `<button type="button" class="b-acc" data-acc="volver" data-i="${i}">Volver a revisar</button>`
        : `<button type="button" class="b-acc pri" data-acc="alertar" data-i="${i}" title="Armar la alerta (A)">${icono("pluma", 14)}Alertar</button>
           <button type="button" class="b-acc" data-acc="interesante" data-i="${i}" title="Interesante, pero no da para alerta (I)">${icono("estrella", 14)}Interesante</button>
           <button type="button" class="b-acc" data-acc="despues" data-i="${i}" title="Dejar para después (D)">${icono("reloj", 14)}Después</button>
           <button type="button" class="quitar" data-acc="descartar" data-i="${i}" title="Descartar: no le interesa (X)" aria-label="Descartar">${icono("x", 15)}</button>`}</span></div>
      <h3>${esc(oracion(a.titulo))}</h3>${porque ? `<p>${esc(porque)}</p>` : ""}<small>${esc(a.fuente)}${otras}</small></article>`;
  }

  function avance(caja) {
    const f = s();
    const n = Object.fromEntries(Object.entries(CAJAS).map(([k, ok]) => [k, universo.filter((a) => ok(estado(a))).length]));
    const etiquetas = Object.keys(CAJAS).map((k) => `${k} ${n[k]}`);
    segmentado(caja.querySelector(".f-caja"), etiquetas, `${f.bandeja} ${n[f.bandeja]}`, (t) => {
      f.bandeja = Object.keys(CAJAS).find((k) => t.startsWith(k)); tope = PASO; App.cerrarDetalle(); dibujar(true);
    });
    const total = universo.length;
    const hechas = total - n["Por revisar"] - n["Para después"];
    caja.querySelector(".av-txt").textContent = !total ? "" : n["Por revisar"] ? `Te faltan ${n["Por revisar"]} de ${total}` : "Todo revisado";
    caja.querySelector(".av-barra i").style.transform = `scaleX(${total ? hechas / total : 0})`;
  }

  // Alertar abre la redaccion con el cliente; las demas sacan la fila de la bandeja con deshacer
  function accion(a, que) {
    if (!a) return;
    const f = s();
    const clientes = Object.keys(a.porque ?? {}).filter((c) => !f.cli || c === f.cli);
    if (que === "descartar") return quitar(a);
    if (que === "volver") {
      if (App.fuera.has(a.id)) App.pedir("deshacer", { id: a.id }).catch((e) => App.fallo(e));
      App.fuera.delete(a.id);
      App.marcar(clave(a), null);
      return dibujar(false);
    }
    App.marcar(clave(a), que, a);
    if (que === "alertar") {
      return App.armar(itemsDe(a), f.cli || clientes[0] || "", a.porque?.[f.cli || clientes[0]] ?? null);
    }
    salir(a, () => {
      App.cerrarDetalle();
      dibujar(false);
      App.aviso(que === "interesante" ? "Guardada en Interesantes, para el reporte" : "Quedó para después", () => { App.marcar(clave(a), null); dibujar(false); });
    });
  }

  // La fila se va hacia la derecha antes de repintar: se ve a donde fue
  function salir(a, listo) {
    const el = raiz.querySelector(`.fila[data-i="${filas.indexOf(a)}"]`);
    if (!el || quieto()) return listo();
    el.style.pointerEvents = "none";
    el.animate([{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateX(12px)" }],
      { duration: 160, easing: "cubic-bezier(.23,1,.32,1)", fill: "forwards" }).onfinish = listo;
  }

  let tope = PASO;
  function vistaAlertas(animar) {
    const f = s();
    const caja = raiz.querySelector(".vista");
    if (!caja.querySelector(".lista")) {
      caja.innerHTML = `<div class="avance"><div class="f-caja"></div><span class="av-txt"></span><span class="av-barra"><i></i></span></div>
        <div class="barra"><div class="f-tipo"></div><input class="buscar" type="search" placeholder="Filtrar esta lista (tecla /)" aria-label="Filtrar esta lista"></div><div class="lista"></div>`;
      segmentado(caja.querySelector(".f-tipo"), ["Todas", ...Object.values(TIPOS)], f.tipo, (t) => { f.tipo = t; tope = PASO; dibujar(true); });
      const q = caja.querySelector(".buscar");
      q.value = f.q ?? "";
      q.oninput = () => { f.q = q.value; tope = PASO; dibujar(false); };
    }
    avance(caja);
    const lista = caja.querySelector(".lista");
    if (!filas.length) {
      lista.innerHTML = `<div class="vacio">${f.bandeja === "Por revisar" && !f.q ? "Revisaste todo lo de este periodo." : "Nada en esta bandeja con estos filtros."}</div>`;
      return;
    }
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

  // La alerta y las demas fuentes del mismo hecho (alerts/que_paso_hoy._grupos): todas van a la redaccion
  const itemsDe = (a) => [item(a.titulo, a.url, a.resumen, a.pais, a.fuente, a.fecha, a.tipo),
    ...(a.fuentes ?? []).map((x) => item(x.titulo, x.url, null, a.pais, x.fuente, x.fecha, "noticia"))];

  function detalle(a) {
    sel = a;
    const f = s();
    const clientes = Object.keys(a.porque ?? {});
    const elegido = f.cli || clientes[0] || "";
    const its = itemsDe(a);
    const det = App.detalle(`
      <div class="marcas">${[TIPOS[a.tipo] ?? "Sesión", PAISES[a.pais], a.fuente].filter(Boolean).map((t) => `<span>${esc(t)}</span>`).join("")}</div>
      <h2>${esc(oracion(a.titulo))}</h2>
      ${clientes.map((c) => `<div class="por"><b>${esc(App.nombre(c))}</b>${esc(a.porque[c])}</div>`).join("")}
      ${a.resumen && !clientes.length ? `<p>${esc(a.resumen.slice(0, 900))}</p>` : ""}
      ${a.ideas?.length ? `<ul>${a.ideas.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
      ${a.fuentes?.length ? `<h3 class="sub-t">El mismo hecho en otras fuentes</h3>${a.fuentes.map((x) => `<div class="ag">${enlace(x.url, x.titulo) || esc(x.titulo)}<small>${esc(x.fuente)}${x.fecha ? `, ${esc(fechaCorta(x.fecha))}` : ""}</small></div>`).join("")}
        <p class="nota">Armar alerta las manda todas a la redacción.</p>` : ""}
      <div class="acciones">${enlace(a.url, a.tipo === "sesion" ? "Ver el video" : "Abrir la fuente", "btn pri")}
        ${bloqueArmar(its, elegido)}
        ${a.tipo !== "sesion" ? `<button type="button" class="btn d-interes">Interesante, sin alerta</button><button type="button" class="btn d-despues">Dejar para después</button>
          <button type="button" class="btn des d-descartar">No le interesa, descartar</button>` : ""}</div>`);
    conectarArmar(det, its, (c) => a.porque?.[c] ?? null);
    App.alCerrar = () => { sel = null; marcar(); };
    marcar();
    if (a.tipo === "sesion") return;
    det.querySelector(".d-armar").addEventListener("click", () => App.marcar(clave(a), "alertar", a));
    det.querySelector(".d-despues").onclick = () => accion(a, "despues");
    det.querySelector(".d-interes").onclick = () => accion(a, "interesante");
    det.querySelector(".d-descartar").onclick = () => quitar(a);
  }

  // El descarte lleva titulo y clientes: el juez de relevancia lo usa como ejemplo de "esto no"
  // Proyectos y normas no tienen id de noticia: solo salen de la bandeja, el filtro no los juzga
  function quitar(a) {
    const f = s();
    const clientes = Object.keys(a.porque ?? {}).filter((c) => !f.cli || c === f.cli);
    App.marcar(clave(a), "descartar", a);
    salir(a, () => {
      if (a.id != null) return descartar(a.id, a.titulo, () => dibujar(false), { titulo: a.titulo, clientes }, () => App.marcar(clave(a), null));
      App.cerrarDetalle();
      dibujar(false);
      App.aviso("Descartada", () => { App.marcar(clave(a), null); dibujar(false); });
    });
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
    pestanas(raiz.querySelector(".tabs"), [["alertas", `Alertas (${r.todas.length})`], ["proyectos", `Proyectos de clientes (${proyectos.length})`]], f.tab, (t) => {
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
      ctrl.innerHTML = `<div class="f-cli"></div><div class="f-ven"></div>`;
      segmentado(ctrl.querySelector(".f-ven"), Object.keys(d.ventanas), f.ven, (t) => { f.ven = t; tope = PASO; dibujar(true); });
      botonesCliente(ctrl.querySelector(".f-cli"), Object.keys(App.d.clientes), f.cli, (v) => { f.cli = v; tope = PASO; dibujar(true); });
      cuerpo.innerHTML = `<div class="aviso"${d.sin_cerebro ? "" : " hidden"}>Todavía no carga la base de relevancia, así que faltan las noticias.</div>
        <div class="kpis"></div><div class="dos"><div><div class="tabs" role="tablist"></div><div class="vista"></div></div><div class="lado"></div></div>`;
      cuerpo.onclick = (e) => {
        const t = e.target;
        if (t.closest("a")) return;
        const ac = t.closest("[data-acc]");
        if (ac) return accion(filas[ac.dataset.i], ac.dataset.acc);
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
    // j/k recorren; a alerta, d deja para despues, x descarta la abierta
    tecla(e) {
      if (s().tab !== "alertas") return;
      const k = e.key.toLowerCase();
      if (sel && filas.includes(sel) && !estado(sel) && "aidx".includes(k)) return accion(sel, { a: "alertar", i: "interesante", d: "despues", x: "descartar" }[k]);
      if (!"jk".includes(e.key)) return;
      const i = Math.max(0, Math.min(filas.length - 1, filas.findIndex((a) => igual(a, sel)) + (e.key === "j" ? 1 : -1)));
      if (i >= tope) { tope += PASO; dibujar(false); }
      if (!filas[i]) return;
      detalle(filas[i]);
      raiz.querySelector(`.fila[data-i="${i}"]`)?.scrollIntoView({ block: "nearest" });
    },
  };
})();

// Descartar con deshacer: lo usan el Panel y Noticias.
function descartar(id, titulo, alCambiar, extra = {}, alDeshacer = () => {}) {
  App.fuera.add(id);
  App.pedir("descartar", { id, ...extra }).catch((e) => App.fallo(e));
  App.cerrarDetalle();
  alCambiar();
  App.aviso(extra.clientes?.length ? `Descartada. El filtro lo tendrá en cuenta para ${extra.clientes.map((c) => App.nombre(c)).join(" y ")}` : `Descartaste: ${titulo}`, () => {
    App.fuera.delete(id);
    App.pedir("deshacer", { id }).catch((e) => App.fallo(e));
    alDeshacer();
    alCambiar();
  });
}
