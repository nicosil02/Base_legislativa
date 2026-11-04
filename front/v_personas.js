// Congresistas y asambleistas: un hemiciclo por camara, bancadas de izquierda a
// derecha (consultas/integrantes.py). Pasar sobre un asiento muestra quien es; el
// clic abre su ficha en un panel lateral (consultas/personas.py).
VISTAS.personas = (() => {
  const f = () => App.f("personas", { id: "", q: "" });
  const CAMARAS = [["senado", "Senado", "PE"], ["diputados", "Cámara de Diputados", "PE"], ["asamblea", "Asamblea Nacional", "EC"]];
  const NOMBRE_CAMARA = Object.fromEntries(CAMARAS.map(([k, t]) => [k, t]));
  const VOTO = { SI: "A favor", NO: "En contra", ABST: "Abstención" };
  // De izquierda a derecha en el hemiciclo; lo que no esta aca va al centro
  const ORIENTACION = ["Revolución Ciudadana", "Pachakutik", "Juntos por el Perú", "Ahora Nación", "Partido del Buen Gobierno",
    "Sin bancada", "Partido Cívico Obras", "Renovación Popular", "Fuerza Popular", "Partido Social Cristiano", "Acción Democrática Nacional"];
  const lugar = (b) => (ORIENTACION.includes(b) ? ORIENTACION.indexOf(b) : ORIENTACION.indexOf("Sin bancada"));
  // colores aproximados de cada bancada; las que no estan toman uno de la lista
  const COLOR = { "Fuerza Popular": "#EE7F1B", "Juntos por el Perú": "#2E8B57", "Renovación Popular": "#2A9FD8",
    "Partido del Buen Gobierno": "#7E57C2", "Partido Cívico Obras": "#D9A900", "Ahora Nación": "#C62828",
    "Acción Democrática Nacional": "#6A3FA0", "Revolución Ciudadana": "#17A2C4", "Pachakutik": "#3E9B3E", "Sin bancada": "#A3AFBA" };
  const RESTO = ["#8D6E63", "#EC407A", "#5C6BC0", "#26A69A", "#78909C"];
  const color = (b) => COLOR[b] ?? (COLOR[b] = RESTO[Object.keys(COLOR).length % RESTO.length]);
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const fichas = new Map();  // ya pedidas: volver a abrir a alguien es instantaneo
  let gente = null, lista = [], porClave = new Map();

  const clave = (p) => `${p.camara}|${p.nombre}`;
  const nombre = (p) => (p.pais === "PE" ? p.nombre.split(",").reverse().join(" ") : p.nombre).replace(/\s+/g, " ").trim();
  const etiqueta = (p) => `${nombre(p)} · ${NOMBRE_CAMARA[p.camara]}, ${p.bancada}`;
  const iniciales = (p) => nombre(p).split(" ").slice(0, 2).map((w) => w[0]).join("");
  const foto = (p, cls) => `<span class="${cls}" style="--c:${color(p.bancada)}">${iniciales(p)}${p.foto ? `<img src="${esc(p.foto)}" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>`;
  const bancada = (b) => `<span class="pb"><i style="background:${color(b)}"></i>${esc(b)}</span>`;

  // Asientos en semicirculo: filas proporcionales al radio, de izquierda a derecha.
  function asientos(n) {
    const filas = Math.max(3, Math.round(Math.sqrt(n / 4)));
    const radios = Array.from({ length: filas }, (_, i) => 0.42 + (0.58 * i) / (filas - 1));
    const suma = radios.reduce((a, b) => a + b, 0);
    const cuantos = radios.map((r) => Math.round((n * r) / suma));
    cuantos[filas - 1] += n - cuantos.reduce((a, b) => a + b, 0);
    const pos = [];
    radios.forEach((r, i) => {
      for (let j = 0; j < cuantos[i]; j++) {
        const a = Math.PI * (1 - (cuantos[i] === 1 ? 0.5 : j / (cuantos[i] - 1)));
        pos.push({ x: r * Math.cos(a), y: r * Math.sin(a), a });
      }
    });
    return { pos: pos.sort((p, q) => q.a - p.a), punto: (0.58 / (filas - 1)) * 0.4 };
  }

  function hemiciclo(miembros, titulo) {
    const cuenta = {};
    miembros.forEach((p) => { cuenta[p.bancada] = (cuenta[p.bancada] ?? 0) + 1; });
    const orden = Object.keys(cuenta).sort((a, b) => lugar(a) - lugar(b) || cuenta[b] - cuenta[a]);
    const sentados = [...miembros].sort((p, q) => orden.indexOf(p.bancada) - orden.indexOf(q.bancada) || nombre(p).localeCompare(nombre(q)));
    const { pos, punto } = asientos(sentados.length);
    return `<section class="hemi"><h2>${esc(titulo)}<span>${sentados.length} escaños · mayoría ${Math.floor(sentados.length / 2) + 1}</span></h2>
      <svg viewBox="-1.12 -1.12 2.24 1.2" role="group" aria-label="${esc(titulo)}">
        ${pos.map((s, i) => `<circle cx="${s.x.toFixed(4)}" cy="${(-s.y).toFixed(4)}" r="${punto.toFixed(4)}" fill="${color(sentados[i].bancada)}"
          data-p="${esc(clave(sentados[i]))}" data-b="${esc(sentados[i].bancada)}" tabindex="0" aria-label="${esc(nombre(sentados[i]))}"></circle>`).join("")}
        <text x="0" y="-0.06" text-anchor="middle" class="hemi-n">${sentados.length}</text></svg>
      <ul class="leyenda">${orden.map((b) => `<li data-b="${esc(b)}"><i style="background:${color(b)}"></i>${esc(b)} <b>${cuenta[b]}</b></li>`).join("")}</ul></section>`;
  }

  // ---- panel de la persona ----
  const mes = (fecha) => fecha.slice(0, 7);
  const nombreMes = (m) => `${MESES[Number(m.slice(5)) - 1].slice(0, 3)} ${m.slice(2, 4)}`;
  const tipoVoto = (v) => (VOTO[v.voto] ? v.voto : "nv");

  function votos(caja, todos) {
    if (!todos.length) { caja.innerHTML = `<div class="vacio">Sin votaciones nominales registradas.</div>`; return; }
    const meses = [...new Set(todos.map((v) => mes(v.fecha)))].reverse();
    const pintar = (m) => {
      const vs = m ? todos.filter((v) => mes(v.fecha) === m) : todos;
      const n = (k) => vs.filter((v) => tipoVoto(v) === k).length;
      const contra = vs.filter((v) => v.contra_bancada);
      caja.querySelector(".v-res").innerHTML = `<div class="barra-votos">${["SI", "NO", "ABST", "nv"].filter(n).map((k) => `<span class="bv-${k}" style="flex:${n(k)}"></span>`).join("")}</div>
        <div class="v-cifras">${["SI", "NO", "ABST", "nv"].map((k) => `<span><i class="bv-${k}"></i>${n(k)} ${(VOTO[k] ?? "no votó").toLowerCase()}</span>`).join("")}</div>
        ${contra.length ? `<p class="nota">${contra.length} ${contra.length === 1 ? "vez" : "veces"} votó distinto a la mayoría de su bancada. Van primero.</p>` : ""}`;
      caja.querySelector(".v-lista").innerHTML = [...contra, ...vs.filter((v) => !v.contra_bancada)].slice(0, 40).map((v) => `<div class="pv">
          <span class="voto bv-${tipoVoto(v)}">${esc(VOTO[v.voto] ?? "No votó")}</span><div><p>${esc(oracion(v.asunto))}</p>
          <small>${esc(fechaCorta(v.fecha))}${v.contra_bancada ? " · contra su bancada" : ""}</small></div></div>`).join("");
    };
    caja.innerHTML = `<div class="v-meses"></div><div class="v-res"></div><div class="v-lista"></div>`;
    const ops = ["Todo", ...meses.map(nombreMes)];
    segmentado(caja.querySelector(".v-meses"), ops, "Todo", (t) => pintar(meses[ops.indexOf(t) - 1]));
    pintar(null);
  }

  const filaPl = (x) => `<div class="pv"><span class="pl-n">${esc(x.pl.split("-")[0].replace(/^0+/, "") || x.pl)}</span><div>
      <p>${esc(oracion(x.titulo ?? ""))}</p><small>${esc(fechaCorta(x.fecha))} · ${esc(x.estado ?? "")}${x.seguido ? " · lo sigues" : ""}</small></div></div>`;
  function proyectos(caja, pls) {
    const grupos = { Presentó: pls.filter((x) => x.primero), "Apoyó con su firma": pls.filter((x) => !x.primero) };
    const pintar = (t) => {
      const xs = grupos[t.replace(/ \(\d+\)$/, "")];
      caja.querySelector(".pr-lista").innerHTML = [...xs.filter((x) => x.seguido), ...xs.filter((x) => !x.seguido)].map(filaPl).join("")
        || `<div class="vacio">Ninguno en este periodo.</div>`;
    };
    caja.innerHTML = `<div class="pr-seg"></div><div class="pr-lista"></div>`;
    const ops = Object.entries(grupos).map(([k, v]) => `${k} (${v.length})`);
    segmentado(caja.querySelector(".pr-seg"), ops, ops[0], pintar);
    pintar(ops[0]);
  }

  function dijo(r) {
    return r.sesiones.map((x) => `<div class="pv dicho"><div><small>${esc(fechaCorta(x.fecha))} · ${esc(x.organo)} ${enlaceIcono(x.url, "Ver la sesión")}</small>
        ${x.trozos.map((t) => `<p>«${esc(t)}»</p>`).join("")}</div></div>`).join("")
      + (r.mesas.length ? `<h3 class="cajon-sub">Mesas técnicas que organizó</h3>${r.mesas.map((m) => `<div class="pv"><div><p>${esc(m.titulo ?? "")}</p>
        <small>${esc(fechaCorta(m.fecha))} ${enlaceIcono(m.url, "Abrir")}</small></div></div>`).join("")}` : "")
      || `<div class="vacio">No aparece en las sesiones transcritas.</div>`;
  }

  function cerrar(raiz) {
    f().id = ""; f().q = "";
    raiz.querySelector(".p-q").value = "";
    raiz.querySelectorAll("circle.elegido").forEach((c) => c.classList.remove("elegido"));
    raiz.querySelector(".cajon-p").classList.remove("abierto");
  }

  async function abrir(raiz, p) {
    f().id = clave(p); f().q = etiqueta(p);
    raiz.querySelectorAll("circle.elegido").forEach((c) => c.classList.remove("elegido"));
    raiz.querySelector(`circle[data-p="${CSS.escape(clave(p))}"]`)?.classList.add("elegido");
    const panel = raiz.querySelector(".cajon-p");
    const pe = p.pais === "PE";
    panel.innerHTML = `<div class="cp-cab">${foto(p, "cp-foto")}<div class="cp-tit"><h2>${esc(nombre(p))}</h2>
        <p>${bancada(p.bancada)} · ${esc(NOMBRE_CAMARA[p.camara])}${p.region ? ` · ${esc(p.region)}` : ""}${p.condicion && p.condicion !== "en ejercicio" ? ` · ${esc(p.condicion)}` : ""}</p>
        ${p.url ? `<a class="nota" href="${esc(p.url)}" target="_blank" rel="noopener">Perfil oficial</a>` : ""}</div>
        <button type="button" class="cp-x" aria-label="Cerrar">${icono("x", 18)}</button></div>
      <div class="cp-resena">${p.resena ? `<p>${esc(p.resena)}</p>` : ""}</div>
      <div class="cp-cifras">${espera(1)}</div><div class="cp-tabs"></div><div class="cp-cuerpo"></div>`;
    panel.classList.add("abierto");
    panel.scrollTop = 0;
    panel.querySelector(".cp-x").onclick = () => cerrar(raiz);
    const k = clave(p);
    let r = fichas.get(k);
    if (!r) {
      try { r = await App.pedir("ficha_persona", { pais: p.pais, persona: p.id }); } catch (e) {
        if (f().id === k) panel.querySelector(".cp-cifras").innerHTML = `<div class="aviso">No se pudo armar la ficha: ${esc(e.message)}</div>`;
        return;
      }
      fichas.set(k, r);
    }
    if (f().id !== k) return;
    const propios = r.pls.filter((x) => x.primero).length;
    panel.querySelector(".cp-cifras").innerHTML = [
      ...(pe ? [[r.pct_alineado != null ? `${r.pct_alineado}%` : "—", "vota con su bancada"], [r.votaciones ?? "—", "votaciones"], [r.ausencias ?? "—", "no votó"]] : []),
      [propios, "proyectos presentados"], [r.pls.length - propios, "apoyó con su firma"],
    ].map(([n, t]) => `<div><b>${n}</b><span>${t}</span></div>`).join("");
    const tabs = [...(pe ? [["Votos", (c) => votos(c, r.votos)]] : []), ["Proyectos", (c) => proyectos(c, r.pls)],
      [`Qué dijo (${r.sesiones.length})`, (c) => { c.innerHTML = dijo(r); }]];
    const cuerpo = panel.querySelector(".cp-cuerpo");
    segmentado(panel.querySelector(".cp-tabs"), tabs.map(([t]) => t), tabs[0][0], (t) => tabs.find(([x]) => x === t)[1](cuerpo));
    tabs[0][1](cuerpo);
    if (!p.resena) {  // la reseña de Wikipedia llega despues, sin frenar lo demas
      const w = p.wiki !== undefined ? p.wiki : (p.wiki = await App.pedir("resena_persona", { pais: p.pais, nombre: p.nombre }).catch(() => null));
      if (w && f().id === k) panel.querySelector(".cp-resena").innerHTML = `<p>${esc(w.texto)}</p><a class="nota" href="${esc(w.url)}" target="_blank" rel="noopener">Reseña de Wikipedia</a>`;
    }
  }

  function tarjeta(raiz) {
    const tip = raiz.querySelector(".p-tip");
    const hemis = raiz.querySelector(".hemis");
    hemis.onpointerover = (e) => {
      // pasar por una bancada de la leyenda resalta sus asientos
      const li = e.target.closest(".leyenda li");
      raiz.querySelectorAll("circle").forEach((c) => c.classList.toggle("apagado", !!li && c.dataset.b !== li.dataset.b));
      const s = e.target.closest("circle[data-p]");
      if (!s) { tip.hidden = true; return; }
      const p = porClave.get(s.dataset.p);
      tip.innerHTML = `${foto(p, "tip-foto")}<div><b>${esc(nombre(p))}</b>${bancada(p.bancada)}<small>${esc(p.region ?? "")}</small></div>`;
      const b = s.getBoundingClientRect(), r = raiz.getBoundingClientRect();
      tip.style.left = `${Math.max(130, Math.min(b.left - r.left + b.width / 2, r.width - 130))}px`;
      tip.style.top = `${b.top - r.top}px`;
      tip.hidden = false;
    };
    hemis.onpointerleave = () => { tip.hidden = true; raiz.querySelectorAll("circle.apagado").forEach((c) => c.classList.remove("apagado")); };
  }

  return {
    titulo: "Congresistas y asambleístas", sub: "Bancadas de izquierda a derecha. Pasa sobre un asiento para ver quién es y haz clic para su ficha.",
    async abrir(cuerpo) {
      cuerpo.innerHTML = `<div class="personas"><div class="barra"><input type="search" class="buscar p-q" list="p-lista" placeholder="Buscar por nombre o apellido" aria-label="Buscar" value="${esc(f().q)}"></div>
        <datalist id="p-lista"></datalist><div class="hemis">${espera(3)}</div><div class="p-tip" hidden></div><aside class="cajon-p" aria-label="Ficha"></aside></div>`;
      const raiz = cuerpo.querySelector(".personas");
      if (!gente) {
        try { gente = await App.pedir("personas"); } catch (e) { raiz.querySelector(".hemis").innerHTML = `<div class="aviso">No se pudo traer la lista: ${esc(e.message)}</div>`; return; }
      }
      lista = gente.filter((p) => !App.pais || p.pais === App.pais);
      porClave = new Map(lista.map((p) => [clave(p), p]));
      raiz.querySelector("#p-lista").innerHTML = lista.map((p) => `<option value="${esc(etiqueta(p))}"></option>`).join("");
      raiz.querySelector(".hemis").innerHTML = CAMARAS.filter(([, , pais]) => !App.pais || pais === App.pais)
        .map(([k, t]) => hemiciclo(lista.filter((p) => p.camara === k), t)).join("")
        + (!App.pais || App.pais === "EC" ? `<p class="nota hemi-nota">Asamblea de Ecuador según Wikipedia: el sitio oficial no responde desde el 4/11/2026.</p>` : "");
      tarjeta(raiz);
      const q = raiz.querySelector(".p-q");
      q.oninput = () => { const p = lista.find((x) => etiqueta(x) === q.value); if (p) abrir(raiz, p); };
      const hemis = raiz.querySelector(".hemis");
      hemis.onclick = (e) => { const s = e.target.closest("circle[data-p]"); if (s) { raiz.querySelector(".p-tip").hidden = true; abrir(raiz, porClave.get(s.dataset.p)); } };
      hemis.onkeydown = (e) => { const s = e.target.closest("circle[data-p]"); if (s && e.key === "Enter") abrir(raiz, porClave.get(s.dataset.p)); };
      raiz.onkeydown = (e) => { if (e.key === "Escape") cerrar(raiz); };
      if (porClave.has(f().id)) abrir(raiz, porClave.get(f().id));
    },
  };
})();
