// Congresistas y asambleistas. Eliges la camara y sale su hemiciclo, bancadas de
// izquierda a derecha (consultas/integrantes.py). Clic en una bancada lista a sus
// miembros; clic en un asiento abre la ficha (consultas/personas.py). El buscador
// acepta una persona o un tema: con un tema pinta quien lo impulsa y como voto cada uno.
VISTAS.personas = (() => {
  const f = () => App.f("personas", { cam: "", id: "", q: "", bancada: "" });
  const CAMARAS = [["senado", "Senado", "PE"], ["diputados", "Cámara de Diputados", "PE"], ["asamblea", "Asamblea Nacional", "EC"]];
  const NOMBRE_CAMARA = Object.fromEntries(CAMARAS.map(([k, t]) => [k, t]));
  const VOTO = { SI: "A favor", NO: "En contra", ABST: "Abstención", BLANCO: "En blanco" };
  const VCOLOR = { SI: "#2E8B57", NO: "#C62828", ABST: "#D9A900", BLANCO: "#7E8A97", nv: "#D5DCE3" };
  // De izquierda a derecha en el hemiciclo; lo que no esta aca va al centro
  const ORIENTACION = ["Revolución Ciudadana", "Pachakutik", "Juntos por el Perú", "Ahora Nación", "Partido Cívico Obras",
    "Partido del Buen Gobierno", "Sin bancada", "Renovación Popular", "Fuerza Popular", "Partido Social Cristiano", "Acción Democrática Nacional"];
  const lugar = (b) => (ORIENTACION.includes(b) ? ORIENTACION.indexOf(b) : ORIENTACION.indexOf("Sin bancada"));
  // el color principal del logo de cada partido
  const COLOR = { "Fuerza Popular": "#E8541F", "Renovación Popular": "#0F6E9C", "Juntos por el Perú": "#5DB320",
    "Ahora Nación": "#E30613", "Partido del Buen Gobierno": "#F9C80E", "Partido Cívico Obras": "#1E7B1E",
    "Acción Democrática Nacional": "#6C2C91", "Revolución Ciudadana": "#3FA9E0", "Pachakutik": "#D7262A",
    "Partido Social Cristiano": "#F7C21A", "Sin bancada": "#A3AFBA" };
  const TEMAS = ["Agricultura", "Ambiente", "Banca", "Comercio", "Construcción", "Consumo masivo", "Deporte", "Educación", "Energía",
    "Farma", "Horeca", "Infraestructura", "Informalidad", "Inmobiliario", "Minería", "Mype", "Pensiones", "Pesca", "Salud",
    "Saneamiento", "Seguros", "Tecnología", "Telecomunicaciones", "Trabajo", "Transporte", "Tributos"];
  const RESTO = ["#8D6E63", "#5C6BC0", "#26A69A", "#78909C"];
  const color = (b) => COLOR[b] ?? (COLOR[b] = RESTO[Object.keys(COLOR).length % RESTO.length]);
  const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const fichas = new Map();  // ya pedidas: volver a abrir a alguien es instantaneo
  const temas = new Map();   // busquedas de tema ya hechas
  let gente = null, porClave = new Map(), tema = null;
  const cierreFuera = new WeakSet();

  const plano = (s) => (s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const clave = (p) => p.id;
  const nombre = (p) => (p.pais === "PE" ? p.nombre.split(",").reverse().join(" ") : p.nombre).replace(/\s+/g, " ").trim();
  const iniciales = (p) => nombre(p).split(" ").slice(0, 2).map((w) => w[0]).join("");
  const foto = (p, cls) => `<span class="${cls}" style="--c:${color(p.bancada)}">${iniciales(p)}${p.foto ? `<img src="${esc(p.foto)}" alt="" loading="lazy" onerror="this.remove()">` : ""}</span>`;
  const bancada = (b) => `<span class="pb"><i style="background:${color(b)}"></i>${esc(b)}</span>`;
  const camaras = () => CAMARAS.filter(([, , pais]) => !App.pais || pais === App.pais);
  const miembros = () => gente.filter((p) => p.camara === f().cam);
  // presidir una comision decide que se agenda: va en la tarjeta
  // titular o suplente de una comision (solo el Senado lo publica)
  const MIEMBRO = /^(Titular|Suplente)$/;
  const integra = (p) => {
    const xs = (p.cargos ?? []).filter((c) => MIEMBRO.test(c.cargo));
    return xs.length ? `<p class="cp-cargo">Integra ${xs.map((c) => `${esc(c.organo.replace(/^Comisión /, "la comisión "))}${c.cargo === "Suplente" ? " (suplente)" : ""}`).join(", ")}</p>` : "";
  };
  const preside = (p) => (p.cargos ?? []).find((c) => c.cargo.startsWith("Presiden"));

  // Asientos en semicirculo: filas proporcionales al radio, de izquierda a derecha.
  function asientos(n) {
    const filas = Math.max(4, Math.ceil(Math.sqrt(n / 3)));
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
    // el punto cabe en el menor espacio entre filas o entre vecinos de una misma fila
    const hueco = Math.min(0.58 / (filas - 1), ...radios.map((r, i) => (cuantos[i] > 1 ? (Math.PI * r) / (cuantos[i] - 1) : 1)));
    return { pos: pos.sort((p, q) => q.a - p.a), punto: hueco * 0.44 };
  }

  function orden(gs) {
    const cuenta = {};
    gs.forEach((p) => { cuenta[p.bancada] = (cuenta[p.bancada] ?? 0) + 1; });
    return { cuenta, bancadas: Object.keys(cuenta).sort((a, b) => lugar(a) - lugar(b) || cuenta[b] - cuenta[a]) };
  }

  function hemiciclo(gs) {
    const { bancadas } = orden(gs);
    const sentados = [...gs].sort((p, q) => bancadas.indexOf(p.bancada) - bancadas.indexOf(q.bancada) || nombre(p).localeCompare(nombre(q)));
    const { pos, punto } = asientos(sentados.length);
    return `<svg viewBox="-1.1 -1.1 2.2 1.22" role="group" aria-label="${esc(NOMBRE_CAMARA[f().cam])}">
      ${pos.map((s, i) => `<circle cx="${s.x.toFixed(4)}" cy="${(-s.y).toFixed(4)}" r="${punto.toFixed(4)}" fill="${color(sentados[i].bancada)}"
        data-p="${esc(clave(sentados[i]))}" data-b="${esc(sentados[i].bancada)}" tabindex="0" aria-label="${esc(nombre(sentados[i]))}"></circle>`).join("")}
      <text x="0" y="-0.1" text-anchor="middle" class="hemi-n">${sentados.length}</text>
      <text x="0" y="-0.01" text-anchor="middle" class="hemi-m">mayoría ${Math.floor(sentados.length / 2) + 1}</text></svg>`;
  }

  // ---- lado derecho: bancadas, o lo que trae un tema ----
  function lado(raiz) {
    const caja = raiz.querySelector(".p-lado");
    const gs = miembros();
    if (tema) return ladoTema(raiz, caja);
    const { cuenta, bancadas } = orden(gs);
    caja.innerHTML = `<h3>Bancadas</h3><ul class="p-bancadas">${bancadas.map((b) => `<li><button type="button" data-b="${esc(b)}" class="${f().bancada === b ? "activa" : ""}">
        <i style="background:${color(b)}"></i><span>${esc(b)}</span><b>${cuenta[b]}</b>
        <s style="--w:${(100 * cuenta[b]) / gs.length}%;--c:${color(b)}"></s></button></li>`).join("")}</ul>
      <p class="nota">De izquierda a derecha según su orientación. Clic en una bancada para ver a sus miembros.</p>`;
    caja.querySelectorAll("[data-b]").forEach((x) => { x.onclick = () => { f().bancada = f().bancada === x.dataset.b ? "" : x.dataset.b; pintar(raiz); }; });
  }

  function ladoTema(raiz, caja) {
    const r = tema.r;
    const nVot = r.votaciones.length;
    caja.innerHTML = `<div class="p-tema-cab"><h3>«${esc(tema.q)}»</h3><button type="button" class="enlace p-quitar">Quitar tema</button></div>
      <p class="p-tema-res">${r.proyectos} ${r.proyectos === 1 ? "proyecto" : "proyectos"} de esta cámara tocan el tema${nVot ? ` · ${nVot} ${nVot === 1 ? "votación" : "votaciones"} en el Pleno` : ""}.</p>
      ${nVot ? `<div class="p-vots"><button type="button" class="p-vot ${tema.v == null ? "activa" : ""}" data-v="">Quién lo impulsa</button>
        ${r.votaciones.map((v, i) => `<button type="button" class="p-vot ${tema.v === i ? "activa" : ""}" data-v="${i}"><small>${esc(fechaCorta(v.fecha))}</small>${esc(oracion(v.asunto))}</button>`).join("")}</div>` : ""}
      ${tema.v != null ? leyendaVoto(r.votaciones[tema.v]) : `<p class="nota">El color fuerte marca a quien presentó o firmó proyectos sobre el tema.</p>`}
      ${r.ejemplos.length ? `<h3 class="p-sub">Proyectos recientes</h3>${r.ejemplos.slice(0, 5).map((x) => `<p class="p-ej"><small>${esc(fechaCorta(x.fecha))}</small> ${esc(oracion(x.titulo ?? ""))}</p>`).join("")}` : ""}`;
    caja.querySelector(".p-quitar").onclick = () => { tema = null; f().q = ""; raiz.querySelector(".p-tema").value = ""; pintar(raiz); };
    caja.querySelectorAll("[data-v]").forEach((x) => { x.onclick = () => { tema.v = x.dataset.v === "" ? null : Number(x.dataset.v); pintar(raiz); }; });
  }

  function leyendaVoto(v) {
    const ids = new Set(miembros().map(clave));
    const n = {};
    Object.entries(v.votos).forEach(([k, x]) => { if (ids.has(k)) { const t = VOTO[x] ? x : "nv"; n[t] = (n[t] ?? 0) + 1; } });
    return `<ul class="p-voto-ley">${["SI", "NO", "ABST", "BLANCO", "nv"].filter((k) => n[k]).map((k) =>
      `<li><i style="background:${VCOLOR[k]}"></i>${VOTO[k] ?? "No votó"} <b>${n[k]}</b></li>`).join("")}</ul>`;
  }

  // ---- asientos y lista de abajo segun lo elegido ----
  function pintar(raiz) {
    const gs = miembros();
    const impulsa = tema ? new Map(tema.r.impulsan.map((x) => [x.id, x.n])) : null;
    const voto = tema && tema.v != null ? tema.r.votaciones[tema.v].votos : null;
    raiz.querySelectorAll(".p-hemi circle").forEach((c) => {
      const p = porClave.get(c.dataset.p);
      const v = voto && (VOTO[voto[c.dataset.p]] ? voto[c.dataset.p] : "nv");
      c.setAttribute("fill", voto ? VCOLOR[v] : color(p.bancada));
      c.classList.toggle("apagado", voto ? false : impulsa ? !impulsa.has(c.dataset.p) : !!f().bancada && p.bancada !== f().bancada);
      c.classList.toggle("elegido", c.dataset.p === f().id);
    });
    lado(raiz);
    let lista, titulo;
    if (impulsa) {
      lista = gs.filter((p) => impulsa.has(clave(p))).sort((p, q) => impulsa.get(clave(q)) - impulsa.get(clave(p)));
      titulo = lista.length ? `Quiénes presentaron o firmaron proyectos sobre «${tema.q}»` : `Nadie de esta cámara tiene proyectos sobre «${tema.q}»`;
    } else {
      lista = gs.filter((p) => !f().bancada || p.bancada === f().bancada).sort((p, q) => lugar(p.bancada) - lugar(q.bancada) || nombre(p).localeCompare(nombre(q)));
      titulo = f().bancada ? `${f().bancada} · ${lista.length}` : `Todos · ${lista.length}`;
    }
    raiz.querySelector(".p-grupo").innerHTML = `<h3>${esc(titulo)}</h3><div class="p-tarjetas">${lista.map((p) =>
      `<button type="button" class="p-tarj" data-p="${esc(clave(p))}">${foto(p, "tip-foto")}<span><b>${esc(nombre(p))}</b>
        <small>${impulsa ? `${impulsa.get(clave(p))} ${impulsa.get(clave(p)) === 1 ? "proyecto" : "proyectos"} · ` : ""}${esc(f().bancada && !impulsa ? p.region ?? "" : p.bancada)}</small>${preside(p) ? `<em class="p-cargo">Preside la ${esc(preside(p).organo.replace(/^Comisión /, "comisión "))}</em>` : ""}</span></button>`).join("")}</div>`;
  }

  // ---- ficha de la persona ----
  const tipoVoto = (v) => (VOTO[v.voto] ? v.voto : "nv");
  const nombreMes = (m) => `${MESES[Number(m.slice(5)) - 1]} ${m.slice(0, 4)}`;
  const distintos = (xs) => [...new Set(xs.filter(Boolean))];

  // Barra de filtros con opciones fijas (sin escribir): cada uno es un <select> con lo que existe en los datos.
  function barra(caja, defs, sel, alCambiar) {
    const vivos = defs.filter((d) => d.ops.length > 1);
    caja.innerHTML = vivos.length ? `<div class="fx">${vivos.map((d) => `<label><span>${d.t}</span>
        <select data-k="${d.k}"><option value="">${d.todos ?? "Todos"}</option>${d.ops.map(([v, t]) => `<option value="${esc(v)}"${sel[d.k] === v ? " selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`).join("")}
      ${vivos.some((d) => sel[d.k]) ? `<button type="button" class="enlace f-limpiar">Limpiar</button>` : ""}</div>` : "";
    caja.querySelectorAll("select").forEach((s) => { s.onchange = () => { sel[s.dataset.k] = s.value; alCambiar(); }; });
    const l = caja.querySelector(".f-limpiar");
    if (l) l.onclick = () => { defs.forEach((d) => { sel[d.k] = ""; }); alCambiar(); };
  }

  function votos(caja, todos, sel, pais) {
    if (!todos.length) { caja.innerHTML = `<div class="vacio">Sin votaciones nominales registradas.</div>`; return; }
    const defs = [
      { k: "tema", t: "Tema", ops: distintos(todos.map((v) => v.tema)).filter((t) => t !== "Otros").sort().map((t) => [t, t]) },
      { k: "mes", t: "Mes", ops: distintos(todos.map((v) => v.fecha.slice(0, 7))).map((m) => [m, nombreMes(m)]) },
      { k: "voto", t: "Cómo votó", ops: ["SI", "NO", "ABST", "BLANCO", "nv"].filter((k) => todos.some((v) => tipoVoto(v) === k)).map((k) => [k, VOTO[k] ?? "No votó"]) },
      { k: "contra", t: "Frente a su bancada", todos: "Todas", ops: [["si", "Votó distinto a su bancada"], ["no", "Votó con su bancada"]] },
    ];
    const vs = todos.filter((v) => (!sel.tema || v.tema === sel.tema) && (!sel.mes || v.fecha.startsWith(sel.mes))
      && (!sel.voto || tipoVoto(v) === sel.voto) && (!sel.contra || (sel.contra === "si") === !!v.contra_bancada));
    const n = (k) => vs.filter((v) => tipoVoto(v) === k).length;
    const tipos = ["SI", "NO", "ABST", "BLANCO", "nv"].filter(n);
    caja.innerHTML = `<div class="f-caja"></div>
      ${vs.length ? `<div class="barra-votos">${tipos.map((k) => `<span class="bv-${k}" style="flex:${n(k)}"></span>`).join("")}</div>
      <div class="v-cifras"><b>${vs.length} ${vs.length === 1 ? "votación" : "votaciones"}</b>${tipos.map((k) => `<span><i class="bv-${k}"></i>${n(k)} ${(VOTO[k] ?? "no votó").toLowerCase()}</span>`).join("")}</div>` : ""}
      <div class="v-lista">${vs.slice(0, 80).map((v) => `<div class="pv">
          <span class="voto bv-${tipoVoto(v)}">${esc(VOTO[v.voto] ?? "No votó")}</span><div><p>${esc(oracion(v.asunto))}</p>
          <small>${esc(fechaCorta(v.fecha))}${v.tema && v.tema !== "Otros" ? ` · ${esc(v.tema)}` : ""}${v.contra_bancada ? ` · <b class="contra">distinto a su bancada</b>` : ""}</small></div></div>`).join("")
        || `<div class="vacio">Ninguna votación con estos filtros.</div>`}</div>
      ${pais === "EC" ? `<p class="nota">Votos del Observatorio Legislativo, hasta el ${esc(fechaCorta(todos[0].fecha))}. Se omiten las votaciones que cargó con error.</p>` : ""}`;
    barra(caja.querySelector(".f-caja"), defs, sel, () => votos(caja, todos, sel, pais));
  }

  const filaPl = (x) => `<div class="pv pv-pl" data-pl="${esc(x.pl)}" tabindex="0" role="button" aria-expanded="false"><span class="pl-n">${esc(String(x.pl).split("-")[0].replace(/^0+/, "") || x.pl)}</span><div>
      <p>${esc(oracion(x.titulo ?? ""))}</p><small>${x.primero ? "Lo presentó" : "Lo firmó"} · ${esc(fechaCorta(x.fecha))} · ${esc(x.estado ?? "")}${x.tema && x.tema !== "Otros" ? ` · ${esc(x.tema)}` : ""}${x.seguido ? " · lo sigues" : ""}</small><span class="pl-mas">Ver quién habló en su debate</span></div></div><div class="pl-debate" hidden></div>`;
  function proyectos(caja, pls, sel, pais) {
    const defs = [
      { k: "tema", t: "Tema", ops: distintos(pls.map((x) => x.tema)).filter((t) => t !== "Otros").sort().map((t) => [t, t]) },
      { k: "rol", t: "Participación", ops: [["p", `Lo presentó (${pls.filter((x) => x.primero).length})`], ["f", `Lo firmó (${pls.filter((x) => !x.primero).length})`]] },
      { k: "estado", t: "Estado", ops: distintos(pls.map((x) => x.estado)).sort().map((e) => [e, oracion(e)]) },
    ];
    const xs = pls.filter((x) => (!sel.tema || x.tema === sel.tema) && (!sel.rol || (sel.rol === "p") === x.primero) && (!sel.estado || x.estado === sel.estado));
    caja.innerHTML = `<div class="f-caja"></div><div class="v-cifras"><b>${xs.length} ${xs.length === 1 ? "proyecto" : "proyectos"}</b></div>
      ${[...xs.filter((x) => x.seguido), ...xs.filter((x) => !x.seguido)].map(filaPl).join("") || `<div class="vacio">Ninguno con estos filtros.</div>`}`;
    barra(caja.querySelector(".f-caja"), defs, sel, () => proyectos(caja, pls, sel, pais));
    caja.querySelectorAll(".pv-pl").forEach((fila) => {
      fila.onclick = () => {
        const d = fila.nextElementSibling, abre = d.hidden;
        d.hidden = !abre; fila.setAttribute("aria-expanded", abre);
        if (abre && !d.innerHTML) debate(d, pais, fila.dataset.pl);
      };
      fila.onkeydown = (e) => { if (e.key === "Enter") fila.click(); };
    });
  }

  const MENCION = "solo lo mencionan";
  const POSTURA = { "a favor": "bv-SI", "en contra": "bv-NO", "con observaciones": "bv-ABST", propone: "bv-PROP", pregunta: "bv-nv", comenta: "bv-nv" };
  const chipPostura = (x) => `<span class="voto ${POSTURA[x] ?? "bv-nv"}">${esc(oracion(x))}</span>`;

  // lo que dijo llega aparte (Gemini lee cada sesion): la ficha no lo espera
  // posturas: Gemini ya las leyo en la corrida diaria (consultas/posturas.precalcular)
  const PESTANA = "Posturas en el Congreso";
  function dijo(caja, r, sel, p) {
    if (!r.dijo) {
      caja.innerHTML = espera(3);
      pedirDijo(r, p).then(() => { if (caja.isConnected && f().id === clave(p)) dijo(caja, r, sel, p); },
        (e) => { if (caja.isConnected) caja.innerHTML = `<div class="aviso">No se pudo traer: ${esc(e.message)}</div>`; });
      return;
    }
    const todas = r.dijo.sesiones;
    const habla = todas.filter((x) => x.postura !== MENCION);
    const defs = [
      { k: "tema", t: "Tema", ops: distintos(habla.map((x) => x.tema)).filter((t) => t !== "Otros").sort().map((t) => [t, t]) },
      { k: "postura", t: "Postura", ops: distintos(habla.map((x) => x.postura)).map((o) => [o, oracion(o)]) },
      { k: "organo", t: "Dónde", ops: distintos(habla.map((x) => x.organo)).sort().map((o) => [o, o]) },
    ];
    const ses = habla.filter((x) => (!sel.tema || x.tema === sel.tema) && (!sel.organo || x.organo === sel.organo) && (!sel.postura || x.postura === sel.postura));
    const mencion = todas.length - habla.length;
    const libre = !sel.tema && !sel.organo && !sel.postura;
    caja.innerHTML = `<div class="f-caja"></div>` + (ses.map((x) => `<div class="pv dicho">${x.postura ? chipPostura(x.postura) : `<span class="voto bv-nv">Sin resumir</span>`}<div>
        ${x.piensa ? `<p class="d-piensa">${esc(x.piensa)}</p>` : (x.trozos ?? []).slice(0, 1).map((t) => `<p>«${esc(t)}»</p>`).join("")}
        <small>${x.sobre ? `Sobre ${esc(x.sobre)} · ` : x.tema && x.tema !== "Otros" ? `${esc(x.tema)} · ` : ""}${esc(fechaCorta(x.fecha))} · ${esc(x.organo)} ${enlaceIcono(x.url, "Ver la sesión")}</small></div></div>`).join("")
      || `<div class="vacio">${todas.length ? "Ninguna postura con estos filtros." : "No interviene en las sesiones transcritas."}</div>`)
      + (mencion && libre ? `<p class="nota">En ${mencion} ${mencion === 1 ? "sesión más solo lo nombran" : "sesiones más solo lo nombran"}, sin que hable.</p>` : "")
      + (r.dijo.mesas.length && libre ? `<h3 class="p-sub">Mesas técnicas que organizó</h3>${r.dijo.mesas.map((m) => `<div class="pv"><div><p>${esc(m.titulo ?? "")}</p>
        <small>${esc(fechaCorta(m.fecha))} ${enlaceIcono(m.url, "Abrir")}</small></div></div>`).join("")}` : "")
      + (habla.some((x) => x.piensa) ? `<p class="nota">Resumido con IA a partir de la transcripción. Abre la sesión para el texto exacto.</p>` : "")
      + (libre ? `<h3 class="p-sub">En medios</h3>` + ((r.dijo.medios ?? []).map((m) => `<div class="pv"><div><p>${esc(m.titulo ?? "")}</p>
        <small>${esc(m.fuente ?? "")} · ${esc(fechaCorta(m.fecha))} ${enlaceIcono(m.url, m.tipo === "entrevista" ? "Ver la entrevista" : "Abrir la nota")}</small></div></div>`).join("")
        || `<div class="vacio">No aparece en las noticias de los últimos 4 meses.</div>`) : "");
    barra(caja.querySelector(".f-caja"), defs, sel, () => dijo(caja, r, sel, p));
  }
  const pedirDijo = (r, p) => (r.pidiendo ??= App.pedir("dijo_persona", { pais: p.pais, persona: p.id, nombre: nombre(p) })
    .then((d) => { r.dijo = d; }, (e) => { r.pidiendo = null; throw e; }));

  // quien hablo del proyecto cuando se sustento o debatio, agrupado por bancada
  const debates = new Map();
  async function debate(caja, pais, pl) {
    caja.innerHTML = `<p class="nota">Buscando el debate en las sesiones transcritas…</p>`;
    let d = debates.get(`${pais}:${pl}`);
    if (!d) {
      try { d = await App.pedir("debate_pl", { pais, pl }); } catch (e) { caja.innerHTML = `<div class="aviso">No se pudo leer: ${esc(e.message)}</div>`; return; }
      debates.set(`${pais}:${pl}`, d);
    }
    if (!d.length) { caja.innerHTML = `<p class="nota">No encontramos su sustentación o debate en las sesiones transcritas.</p>`; return; }
    const grupos = {};
    d.forEach((x) => { (grupos[x.bancada ?? "Ejecutivo, invitados y otros"] ??= []).push(x); });
    caja.innerHTML = Object.entries(grupos).sort(([a], [b]) => lugar(a) - lugar(b)).map(([b, xs]) => `<div class="db-grupo">
        <h4>${COLOR[b] ? bancada(b) : esc(b)}</h4>${xs.map((x) => `<div class="db-dicho">${chipPostura(x.postura)}<div>
          <p><b>${esc(x.nombre ? nombre({ ...x, pais }) : oracion(x.orador))}</b> <small>${esc(x.rol)}</small></p><p>${esc(x.dijo)}</p>
          <small>${esc(fechaCorta(x.fecha))} · ${esc(x.organo)} ${enlaceIcono(x.url, "Ver la sesión")}</small></div></div>`).join("")}</div>`).join("")
      + `<p class="nota">Resumen hecho con IA a partir de la transcripción.</p>`;
  }

  // temas de sus proyectos (los que presento pesan el doble): lo que impulsa
  function posturas(r) {
    const n = {};
    r.pls.forEach((x) => { if (x.tema && x.tema !== "Otros") n[x.tema] = (n[x.tema] ?? 0) + (x.primero ? 2 : 1); });
    (r.dijo?.sesiones ?? []).forEach((x) => { if (x.tema && x.tema !== "Otros" && x.postura !== MENCION) n[x.tema] = (n[x.tema] ?? 0) + 1; });
    return Object.entries(n).sort((a, b) => b[1] - a[1]).slice(0, 7).map(([t]) => t);
  }

  function cerrar(raiz) {
    f().id = "";
    raiz.querySelector(".cajon-p").classList.remove("abierto");
    raiz.querySelectorAll("circle.elegido").forEach((c) => c.classList.remove("elegido"));
  }

  async function abrir(raiz, p) {
    f().id = clave(p);
    raiz.querySelectorAll("circle.elegido").forEach((c) => c.classList.remove("elegido"));
    raiz.querySelector(`circle[data-p="${CSS.escape(clave(p))}"]`)?.classList.add("elegido");
    const panel = raiz.querySelector(".cajon-p");
    const enlace = p.url ? `<a class="nota" href="${esc(p.url)}" target="_blank" rel="noopener">${p.url.includes("observatorio") ? "Perfil en el Observatorio Legislativo" : "Perfil oficial"}</a>` : "";
    panel.innerHTML = `<div class="cp-cab">${foto(p, "cp-foto")}<div class="cp-tit"><h2>${esc(nombre(p))}</h2>
        <p>${bancada(p.bancada)} · ${esc(NOMBRE_CAMARA[p.camara])}${p.region ? ` · ${esc(p.region)}` : ""}${p.condicion && p.condicion !== "en ejercicio" ? ` · ${esc(p.condicion)}` : ""}</p>
        ${(p.cargos ?? []).filter((c) => !MIEMBRO.test(c.cargo)).map((c) => `<p class="cp-cargo"><b>${esc(c.cargo)}</b> ${esc(c.organo)}</p>`).join("")}
        ${integra(p)}
        ${enlace}</div>
        <button type="button" class="cp-x" aria-label="Cerrar">${icono("x", 18)}</button></div>
      <div class="cp-resena">${p.resena ? `<p>${esc(p.resena)}</p>` : ""}</div>
      <div class="cp-cifras">${espera(1)}</div><div class="cp-temas"></div>
      <div class="cp-tabs"></div><div class="cp-cuerpo"></div>`;
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
      ...(r.votaciones ? [[r.pct_alineado != null ? `${r.pct_alineado}%` : "—", "vota con su bancada"], [r.votaciones, "votaciones"], [r.ausencias, "no votó"]] : []),
      [propios, "proyectos presentados"], [r.pls.length - propios, "firmó con otros"],
    ].map(([n, t]) => `<div><b>${n}</b><span>${t}</span></div>`).join("");
    const sel = {};
    const tabs = [["Votos", (c) => votos(c, r.votos, sel, p.pais)], ["Proyectos", (c) => proyectos(c, r.pls, sel, p.pais)],
      [PESTANA, (c) => dijo(c, r, sel, p)]].filter(([t]) => t !== "Votos" || r.votos.length);
    const cuerpo = panel.querySelector(".cp-cuerpo");
    let actual = tabs[0];
    const ir = (t) => {
      actual = tabs.find(([y]) => y === t);
      segmentado(panel.querySelector(".cp-tabs"), tabs.map(([x]) => x), t, ir);
      actual[1](cuerpo);
    };
    ir(actual[0]);
    // temas que trabaja: sus proyectos y sus posturas (estas llegan un instante despues)
    const caja = panel.querySelector(".cp-temas");
    const chips = () => {
      const ts = posturas(r);
      caja.innerHTML = ts.length ? `<span class="nota">Temas que trabaja</span>${ts.map((t) => `<button type="button" class="chip-tema${sel.tema === t ? " activa" : ""}" data-t="${esc(t)}">${esc(t)}</button>`).join("")}` : "";
      // un tema filtra todas las pestañas; abre sus posturas si las hay, si no sus proyectos
      caja.querySelectorAll(".chip-tema").forEach((b) => { b.onclick = () => {
        sel.tema = sel.tema === b.dataset.t ? "" : b.dataset.t;
        caja.querySelectorAll(".chip-tema").forEach((x) => x.classList.toggle("activa", x.dataset.t === sel.tema));
        const hay = (r.dijo?.sesiones ?? []).some((x) => x.tema === sel.tema && x.postura !== MENCION);
        ir(!sel.tema ? actual[0] : hay ? PESTANA : "Proyectos");
      }; });
    };
    chips();
    pedirDijo(r, p).then(() => { if (f().id === k) chips(); }, () => {});
    if (!p.resena) {  // la reseña de Wikipedia llega despues, sin frenar lo demas
      const w = p.wiki !== undefined ? p.wiki : (p.wiki = await App.pedir("resena_persona", { pais: p.pais, nombre: p.nombre }).catch(() => null));
      if (w && f().id === k) panel.querySelector(".cp-resena").innerHTML = `<p>${esc(w.texto)}</p><a class="nota" href="${esc(w.url)}" target="_blank" rel="noopener">Reseña de Wikipedia</a>`;
    }
  }

  async function buscarTema(raiz, q) {
    f().q = q;
    const k = `${f().cam}|${plano(q)}`;
    raiz.querySelector(".p-lado").innerHTML = espera(2);
    let r = temas.get(k);
    if (!r) {
      try { r = await App.pedir("por_tema", { pais: porPais(), camara: f().cam, q }); } catch (e) {
        raiz.querySelector(".p-lado").innerHTML = `<div class="aviso">No se pudo buscar: ${esc(e.message)}</div>`; return;
      }
      temas.set(k, r);
    }
    tema = { q, r, v: null };
    f().bancada = "";
    pintar(raiz);
  }
  const porPais = () => CAMARAS.find(([k]) => k === f().cam)[2];

  function escena(raiz) {
    const hemi = raiz.querySelector(".p-hemi");
    hemi.innerHTML = hemiciclo(miembros());
    raiz.querySelectorAll(".p-cam").forEach((b) => b.classList.toggle("activa", b.dataset.cam === f().cam));
    raiz.querySelector("#p-lista").innerHTML = miembros().map((p) => `<option value="${esc(nombre(p))}"></option>`).join("");
    const q = f().q;
    tema = null;
    if (q && !miembros().some((p) => nombre(p) === q)) buscarTema(raiz, q); else pintar(raiz);
  }

  function tarjeta(raiz) {
    const tip = raiz.querySelector(".p-tip");
    const hemi = raiz.querySelector(".p-hemi");
    hemi.onpointerover = (e) => {
      const s = e.target.closest("circle[data-p]");
      if (!s) { tip.hidden = true; return; }
      const p = porClave.get(s.dataset.p);
      const v = tema && tema.v != null ? tema.r.votaciones[tema.v].votos[s.dataset.p] : undefined;
      tip.innerHTML = `${foto(p, "tip-foto")}<div><b>${esc(nombre(p))}</b>${bancada(p.bancada)}<small>${esc(p.region ?? "")}${v !== undefined ? ` · ${VOTO[v] ?? "no votó"}` : ""}</small></div>`;
      const b = s.getBoundingClientRect(), r = raiz.getBoundingClientRect();
      tip.style.left = `${Math.max(130, Math.min(b.left - r.left + b.width / 2, r.width - 130))}px`;
      tip.style.top = `${b.top - r.top}px`;
      tip.hidden = false;
    };
    hemi.onpointerleave = () => { tip.hidden = true; };
  }

  return {
    titulo: "Congresistas y asambleístas", sub: "Elige la cámara. Con un tema ves quién lo impulsa y cómo votó cada uno.",
    async abrir(cuerpo) {
      cuerpo.innerHTML = `<div class="personas"><div class="p-arriba"><div class="p-camaras"></div>
          <form class="p-busca fx"><label><span>Persona</span><input type="search" class="buscar p-q" list="p-lista" placeholder="Escribe un nombre y elige" aria-label="Persona"></label>
          <label><span>Tema</span><select class="p-tema"><option value="">Ninguno</option>${TEMAS.map((t) => `<option${f().q === t ? " selected" : ""}>${t}</option>`).join("")}</select></label></form></div>
          <datalist id="p-lista"></datalist>
        <div class="p-escena"><div class="p-hemi">${espera(2)}</div><aside class="p-lado"></aside></div>
        <section class="p-grupo"></section><div class="p-tip" hidden></div><aside class="cajon-p" aria-label="Ficha"></aside></div>`;
      const raiz = cuerpo.querySelector(".personas");
      if (!gente) {
        try { gente = await App.pedir("personas"); } catch (e) { raiz.querySelector(".p-hemi").innerHTML = `<div class="aviso">No se pudo traer la lista: ${esc(e.message)}</div>`; return; }
      }
      porClave = new Map(gente.map((p) => [clave(p), p]));
      if (!camaras().some(([k]) => k === f().cam)) { f().cam = camaras()[0][0]; f().bancada = ""; }
      raiz.querySelector(".p-camaras").innerHTML = camaras().map(([k, t, pais]) => `<button type="button" class="p-cam" data-cam="${k}">
          <span>${pais === "PE" ? "Perú" : "Ecuador"}</span><b>${esc(t)}</b><small>${gente.filter((p) => p.camara === k).length} escaños</small></button>`).join("");
      raiz.querySelectorAll(".p-cam").forEach((b) => { b.onclick = () => { if (f().cam === b.dataset.cam) return; f().cam = b.dataset.cam; f().bancada = ""; cerrar(raiz); escena(raiz); }; });
      tarjeta(raiz);
      const q = raiz.querySelector(".p-q");
      const persona = () => miembros().find((x) => nombre(x) === q.value.trim()) ?? miembros().find((x) => plano(nombre(x)).includes(plano(q.value.trim())));
      q.oninput = () => { if (miembros().some((x) => nombre(x) === q.value)) { abrir(raiz, persona()); q.value = ""; } };
      raiz.querySelector(".p-busca").onsubmit = (e) => { e.preventDefault(); const p = q.value.trim() && persona(); if (p) { abrir(raiz, p); q.value = ""; } };
      const selTema = raiz.querySelector(".p-tema");
      selTema.onchange = () => { if (selTema.value) buscarTema(raiz, selTema.value); else { tema = null; f().q = ""; pintar(raiz); } };
      const abrirDe = (e) => { const s = e.target.closest("[data-p]"); if (s) { raiz.querySelector(".p-tip").hidden = true; abrir(raiz, porClave.get(s.dataset.p)); } };
      raiz.querySelector(".p-hemi").onclick = abrirDe;
      raiz.querySelector(".p-grupo").onclick = abrirDe;
      raiz.querySelector(".p-hemi").onkeydown = (e) => { if (e.key === "Enter") abrirDe(e); };
      raiz.onkeydown = (e) => { if (e.key === "Escape") cerrar(raiz); };
      // clic fuera de la ficha la cierra. En la app la vista vive en un shadow DOM: se escucha
      // en su raiz (document no ve dentro y retarget el clic al host). Un oyente por raiz.
      const nodo = raiz.getRootNode();
      if (!cierreFuera.has(nodo)) {
        cierreFuera.add(nodo);
        nodo.addEventListener("pointerdown", (e) => {
          const r = nodo.querySelector(".personas");
          if (r && f().id && !e.target.closest(".cajon-p, [data-p], .p-busca")) cerrar(r);
        });
      }
      escena(raiz);
      if (porClave.has(f().id)) abrir(raiz, porClave.get(f().id));
    },
  };
})();
