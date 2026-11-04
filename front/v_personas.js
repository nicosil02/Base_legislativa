// Congresistas y asambleistas: un hemiciclo por camara con sus bancadas
// (consultas/integrantes.py); clic en un asiento abre su ficha (consultas/personas.py):
// foto, reseña, proyectos que presento o apoyo, votos por mes, lo que dijo y sus mesas.
VISTAS.personas = (() => {
  const f = () => App.f("personas", { id: "", q: "" });
  const CAMARAS = [["senado", "Senado", "PE"], ["diputados", "Cámara de Diputados", "PE"], ["asamblea", "Asamblea Nacional", "EC"]];
  const NOMBRE_CAMARA = Object.fromEntries(CAMARAS.map(([k, t]) => [k, t]));
  const VOTO = { SI: "A favor", NO: "En contra", ABST: "Abstención" };
  // colores aproximados de cada bancada; las que no estan toman uno de la lista
  const COLOR = { "Fuerza Popular": "#EE7F1B", "Juntos por el Perú": "#2E8B57", "Renovación Popular": "#2A9FD8",
    "Partido del Buen Gobierno": "#7E57C2", "Partido Cívico Obras": "#D9A900", "Ahora Nación": "#C62828",
    "Acción Democrática Nacional": "#6A3FA0", "Revolución Ciudadana": "#17A2C4", "Pachakutik": "#3E9B3E", "Sin bancada": "#A3AFBA" };
  const RESTO = ["#8D6E63", "#EC407A", "#5C6BC0", "#26A69A", "#78909C"];
  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  let gente = null;

  const nombre = (p) => (p.pais === "PE" ? p.nombre.split(",").reverse().join(" ") : p.nombre).replace(/\s+/g, " ").trim();
  const etiqueta = (p) => `${nombre(p)} · ${NOMBRE_CAMARA[p.camara]}, ${p.bancada}`;
  const iniciales = (p) => nombre(p).split(" ").slice(0, 2).map((w) => w[0]).join("");
  const foto = (p, cls) => `<span class="${cls}" style="--c:${color(p.bancada)}">${iniciales(p)}${p.foto ? `<img src="${esc(p.foto)}" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>`;
  function color(b) {
    if (COLOR[b]) return COLOR[b];
    return (COLOR[b] = RESTO[Object.keys(COLOR).length % RESTO.length]);
  }

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
    return { pos: pos.sort((p, q) => q.a - p.a), punto: 0.58 / (filas - 1) * 0.4 };
  }

  function hemiciclo(miembros, titulo) {
    const cuenta = {};
    miembros.forEach((p) => { cuenta[p.bancada] = (cuenta[p.bancada] ?? 0) + 1; });
    const orden = Object.keys(cuenta).sort((a, b) => (a === "Sin bancada") - (b === "Sin bancada") || cuenta[b] - cuenta[a]);
    const lista = [...miembros].sort((p, q) => orden.indexOf(p.bancada) - orden.indexOf(q.bancada) || nombre(p).localeCompare(nombre(q)));
    const { pos, punto } = asientos(lista.length);
    const mitad = Math.floor(lista.length / 2) + 1;
    return `<section class="hemi"><h2>${esc(titulo)} <span>${lista.length} integrantes, mayoría ${mitad}</span></h2>
      <svg viewBox="-1.12 -1.12 2.24 1.22" role="group" aria-label="${esc(titulo)}">
        ${pos.map((s, i) => `<circle cx="${s.x.toFixed(4)}" cy="${(-s.y).toFixed(4)}" r="${punto.toFixed(4)}" fill="${color(lista[i].bancada)}"
          data-p="${esc(lista[i].camara + "|" + lista[i].nombre)}" tabindex="0"><title>${esc(nombre(lista[i]))}, ${esc(lista[i].bancada)}</title></circle>`).join("")}
        <text x="0" y="-0.08" text-anchor="middle" class="hemi-n">${lista.length}</text></svg>
      <ul class="leyenda">${orden.map((b) => `<li><i style="background:${color(b)}"></i>${esc(b)} <b>${cuenta[b]}</b></li>`).join("")}</ul></section>`;
  }

  // ---- ficha ----
  const mes = (fecha) => fecha.slice(0, 7);
  const nombreMes = (m) => `${MESES[Number(m.slice(5)) - 1]} ${m.slice(0, 4)}`;
  const reparto = (vs) => ["SI", "NO", "ABST", ""].map((k) => [k, vs.filter((v) => (VOTO[v.voto] ? v.voto : "") === k).length]);

  function votos(caja, todos) {
    const meses = [...new Set(todos.map((v) => mes(v.fecha)))];
    const pintar = (m) => {
      const vs = m ? todos.filter((v) => mes(v.fecha) === m) : todos;
      const contra = vs.filter((v) => v.contra_bancada);
      const r = reparto(vs);
      caja.querySelector(".v-resumen").innerHTML = `<div class="barra-votos">${r.filter(([, n]) => n).map(([k, n]) =>
          `<span class="bv-${k || "nv"}" style="flex:${n}" title="${esc(VOTO[k] ?? "No votó")}: ${n}"></span>`).join("")}</div>
        <p class="nota">${r.map(([k, n]) => `${n} ${(VOTO[k] ?? "no votó").toLowerCase()}`).join(", ")}${contra.length ? `. ${contra.length} contra la mayoría de su bancada, van primero` : ""}</p>`;
      caja.querySelector(".v-lista").innerHTML = [...contra, ...vs.filter((v) => !v.contra_bancada)].slice(0, 30).map((v) => `<article class="fila"><div class="marcas"><span>${esc(fechaCorta(v.fecha))}</span>
          <span class="voto bv-${VOTO[v.voto] ? v.voto : "nv"}">${esc(VOTO[v.voto] ?? "No votó")}</span>${v.contra_bancada ? `<span class="cli">Contra su bancada</span>` : ""}</div><p>${esc(oracion(v.asunto))}</p></article>`).join("")
        + (vs.length > 30 ? `<p class="nota">Y ${vs.length - 30} votaciones más en este periodo.</p>` : "");
    };
    if (!todos.length) { caja.innerHTML = `<div class="vacio">Sin votaciones nominales registradas.</div>`; return; }
    caja.innerHTML = `<div class="v-meses"></div><div class="v-resumen"></div><div class="v-lista"></div>`;
    const ops = ["Todo el periodo", ...meses.reverse().map(nombreMes)];
    segmentado(caja.querySelector(".v-meses"), ops, ops[0], (t) => pintar(meses[ops.indexOf(t) - 1]));
    pintar(null);
  }

  const filaPl = (x) => `<article class="fila pl"><div class="marcas"><span>${esc(x.pl)}</span><span>${esc(fechaCorta(x.fecha))}</span>
      ${x.seguido ? `<span class="cli">${icono("estrella", 12)}Lo sigues</span>` : ""}</div>
      <h3>${esc(oracion(x.titulo ?? ""))}</h3><small>${esc(x.estado ?? "")}</small></article>`;
  const listaPl = (xs, vacio) => {
    const orden = [...xs.filter((x) => x.seguido), ...xs.filter((x) => !x.seguido)];
    return orden.map((x, i) => (i === 6 ? `<details class="mas-f"><summary>Ver los otros ${orden.length - 6}</summary>` : "") + filaPl(x)).join("")
      + (orden.length > 6 ? "</details>" : "") || `<div class="vacio">${vacio}</div>`;
  };

  async function ficha(caja, p) {
    const pe = p.pais === "PE";
    caja.innerHTML = `<button type="button" class="btn p-volver">← Volver a ${esc(NOMBRE_CAMARA[p.camara])}</button>
      <header class="p-cab">${foto(p, "p-foto")}<div><h2>${esc(nombre(p))}</h2>
        <div class="marcas"><span>${esc(NOMBRE_CAMARA[p.camara])}, ${esc(PAISES[p.pais])}</span><span class="bancada"><i style="background:${color(p.bancada)}"></i>${esc(p.bancada)}</span>
          ${p.region ? `<span>${esc(p.region)}</span>` : ""}${p.condicion && p.condicion !== "en ejercicio" ? `<span class="cli">${esc(p.condicion)}</span>` : ""}
          ${p.url ? enlaceIcono(p.url, "Perfil oficial") : ""}</div>
        ${p.resena ? `<p class="p-resena">${esc(p.resena)}</p>` : ""}</div></header>
      <div class="p-datos">${espera(4)}</div>`;
    caja.querySelector(".p-volver").onclick = () => { f().id = ""; f().q = ""; App.ir("personas"); };
    const resena = caja.querySelector(".p-resena");
    if (resena) resena.onclick = () => resena.classList.toggle("abierta");
    App.$(".main").scrollTop = 0;
    let r;
    try { r = await App.pedir("ficha_persona", { pais: p.pais, persona: p.id, nombre: p.nombre, con_resena: !!p.resena }); } catch (e) { caja.querySelector(".p-datos").innerHTML = `<div class="aviso">No se pudo armar la ficha: ${esc(e.message)}</div>`; return; }
    if (f().id !== `${p.camara}|${p.nombre}`) return;
    const propios = r.pls.filter((x) => x.primero), apoyos = r.pls.filter((x) => !x.primero);
    if (r.wiki && !p.resena) {
      caja.querySelector(".p-cab > div").insertAdjacentHTML("beforeend", `<p class="p-resena">${esc(r.wiki.texto)}</p><small class="nota">Reseña de <a href="${esc(r.wiki.url)}" target="_blank" rel="noopener">Wikipedia</a></small>`);
      const w = caja.querySelector(".p-resena");
      w.onclick = () => w.classList.toggle("abierta");
    }
    const datos = caja.querySelector(".p-datos");
    datos.innerHTML = `<div class="kpis"></div>
      ${pe ? `<h2 class="grupo-t">Votos en el Pleno por periodo <span>cómo votó cada mes</span></h2><div class="p-votos"></div>` : ""}
      <div class="dos"><div><h2 class="grupo-t">Proyectos que presentó <span>${propios.length}, como primer firmante</span></h2>${listaPl(propios, "No presentó proyectos como primer firmante.")}</div>
        <div><h2 class="grupo-t">Proyectos que apoyó con su firma <span>${apoyos.length}</span></h2>${listaPl(apoyos, "No firmó proyectos de otros.")}</div></div>
      <h2 class="grupo-t">Qué dijo en las sesiones <span>${r.sesiones.length}, las más recientes donde se le nombra (la transcripción automática puede escribir mal los apellidos)</span></h2>
      ${r.sesiones.map((x) => `<article class="fila"><div class="marcas"><span>${esc(fechaCorta(x.fecha))}</span><span>${esc(x.organo)}</span>
          <span>${x.menciones} ${x.menciones === 1 ? "mención" : "menciones"}</span>${enlaceIcono(x.url, "Ver la sesión")}</div>
          ${x.trozos.map((t) => `<p>«${esc(t)}»</p>`).join("")}</article>`).join("") || `<div class="vacio">No aparece en las sesiones transcritas.</div>`}
      ${r.mesas.length ? `<h2 class="grupo-t">Mesas técnicas que organizó <span>${r.mesas.length}</span></h2>
      ${r.mesas.map((m) => `<article class="fila"><div class="marcas"><span>${esc(fechaCorta(m.fecha))}</span>${enlaceIcono(m.url, "Abrir")}</div><h3>${esc(m.titulo ?? "")}</h3></article>`).join("")}` : ""}`;
    kpis(datos.querySelector(".kpis"), [
      ...(pe ? [[r.pct_alineado != null ? `${r.pct_alineado} %` : "—", "Vota con su bancada", `en ${r.votaciones} votaciones del Pleno`],
        [r.ausencias ?? "—", "No votó", "ausente, licencia o sin respuesta"]] : []),
      [propios.length, "Proyectos presentados", pe ? "periodo 2026-2031" : "periodo 2025-2029"],
      [apoyos.length, "Proyectos que apoyó", "con su firma"],
    ]);
    if (pe) votos(datos.querySelector(".p-votos"), r.votos);
    entrar(datos.querySelectorAll(".fila"));
  }

  return {
    titulo: "Congresistas y asambleístas", sub: "Cómo se reparten las bancadas. Haz clic en un asiento para ver qué presentó, qué apoyó y cómo votó.",
    async abrir(cuerpo) {
      cuerpo.innerHTML = `<div class="barra filtros"><label class="campo grande">Buscar por nombre
          <input type="search" class="p-q" list="p-lista" style="min-width:min(30rem,90vw)" placeholder="Escribe un apellido" value="${esc(f().q)}"></label></div>
        <datalist id="p-lista"></datalist><div class="p-caja">${espera(3)}</div>`;
      const caja = cuerpo.querySelector(".p-caja");
      if (!gente) {
        try { gente = await App.pedir("personas"); } catch (e) { caja.innerHTML = `<div class="aviso">No se pudo traer la lista: ${esc(e.message)}</div>`; return; }
      }
      const lista = gente.filter((p) => !App.pais || p.pais === App.pais);
      cuerpo.querySelector("#p-lista").innerHTML = lista.map((p) => `<option value="${esc(etiqueta(p))}"></option>`).join("");
      const abrir = (p) => { f().id = `${p.camara}|${p.nombre}`; f().q = etiqueta(p); ficha(caja, p); };
      const q = cuerpo.querySelector(".p-q");
      q.oninput = () => { const p = lista.find((x) => etiqueta(x) === q.value); if (p) abrir(p); };
      const elegido = lista.find((x) => `${x.camara}|${x.nombre}` === f().id);
      if (elegido) return ficha(caja, elegido);
      caja.innerHTML = `<div class="hemis">${CAMARAS.filter(([, , pais]) => !App.pais || pais === App.pais)
          .map(([k, t]) => hemiciclo(lista.filter((p) => p.camara === k), t)).join("")}</div>
        ${!App.pais || App.pais === "EC" ? `<p class="nota">Asamblea de Ecuador según Wikipedia: el sitio oficial de la Asamblea no responde desde el 4 de noviembre de 2026. Bancadas y salidas pueden ir con atraso.</p>` : ""}`;
      caja.onclick = caja.onkeydown = (e) => {
        if (e.type === "keydown" && e.key !== "Enter") return;
        const s = e.target.closest("[data-p]");
        if (s) abrir(lista.find((x) => `${x.camara}|${x.nombre}` === s.dataset.p));
      };
    },
  };
})();
