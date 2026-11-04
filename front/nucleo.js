// Nucleo de la interfaz: menu, rutas, pedidos al servidor y piezas comunes.
// Los archivos v_*.js agregan una entrada a VISTAS. Todo texto pasa por esc():
// viene de noticias y normas, no es de confianza.
const PAISES = { PE: "Perú", EC: "Ecuador" };
const PASO = 60;
const VIGENCIA_MS = 5 * 60 * 1000;
const VISTAS = {};
const quieto = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const web = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : null);
const miles = (n) => String(n).replace(/\B(?=(\d{3})+$)/g, ".");
const fechaCorta = (f) => (f ? String(f).slice(0, 10).split("-").reverse().join("/") : "");
const enlace = (u, t, clase = "") => (web(u) ? `<a class="${clase}" href="${web(u)}" target="_blank" rel="noopener">${esc(t)}</a>` : "");
const unicos = (lista) => [...new Set(lista.filter((v) => v !== null && v !== undefined && String(v).trim()))].sort((a, b) => String(a).localeCompare(String(b), "es"));
const plural = (n, s, p = `${s}s`) => `${miles(n)} ${n === 1 ? s : p}`;
// Los titulos del Congreso llegan en mayusculas: gritan y cuestan leer
const oracion = (t) => String(t ?? "").split(": ").map((s) => (s.length > 12 && s === s.toUpperCase() ? s.charAt(0) + s.slice(1).toLowerCase() : s)).join(": ");

const ICONOS = {
  inicio: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
  micro: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  doc: '<path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 13h6M9 17h6"/>',
  cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  diario: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h10M7 12h10M7 16h6"/>',
  pluma: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  lista: '<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
  gente: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
  persona: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  buscar: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  lado: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  fuera: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v6H4V6h6"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  reloj: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  estrella: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>',
};
const icono = (k, n = 18) => `<svg width="${n}" height="${n}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONOS[k] ?? ""}</svg>`;
const enlaceIcono = (u, t) => (web(u) ? `<a class="fuente" href="${web(u)}" target="_blank" rel="noopener" title="${esc(t)}" aria-label="${esc(t)}">${icono("fuera", 15)}</a>` : "");

// Rutas por pais: "proyectos" + "pe" = "proyectos_pe"
const base = (ruta) => String(ruta ?? "").replace(/_(pe|ec)$/, "");
const paisDeRuta = (ruta) => (String(ruta ?? "").match(/_(pe|ec)$/)?.[1] ?? "").toUpperCase();

const App = {
  raiz: null, d: null, ruta: null, secciones: {}, fuera: new Set(), enviar: () => {}, filtros: {},
  bandeja: {}, pendientes: {}, seguidos: new Set(), siguiendo: 0,
  // Seguir un PL: aviso por Telegram cuando cambie de estado (alerts/pls_seguidos.py)
  async seguir(pais, p, si) {
    const k = `${pais}:${p.pl}`;
    if (si) this.seguidos.add(k); else this.seguidos.delete(k);
    this.siguiendo++;
    try { await this.pedir("seguir_pl", { pais, pl: p.pl, si, titulo: p.titulo, estado: p.estado, url: p.url }); }
    catch (e) { if (si) this.seguidos.delete(k); else this.seguidos.add(k); this.fallo(e); }
    this.siguiendo--;
  },
  // Bandeja del analista: estado null deshace
  // a: el item del Panel; se guarda lo que necesita el espacio por cliente
  marcar(clave, estado, a) {
    const item = a && { titulo: a.titulo, url: a.url ?? null, pais: a.pais ?? null, resumen: a.resumen ?? null, porque: a.porque ?? {}, tipo: a.tipo };
    if (estado) this.bandeja[clave] = { estado, fecha: new Date().toISOString() }; else delete this.bandeja[clave];
    this.pendientes[clave] = this.bandeja[clave];
    this.pedir("bandeja", { clave, estado, titulo: a?.titulo, item })
      .then(() => { if (this.pendientes[clave] === this.bandeja[clave]) delete this.pendientes[clave]; })
      .catch((e) => this.fallo(e));
  },
  pais: localStorage.getItem("vali:pais") ?? "",  // "" es ambos

  $(s) { return this.raiz.querySelector(s); },
  nombre(slug) { return this.d.clientes[slug]?.nombre ?? slug; },

  // Una peticion a la vez: el valor del disparador se pisa si van dos juntas.
  cola: [], enCurso: null, sigId: 1,
  pedir(tipo, args = {}, alFondo = false) {
    return new Promise((ok, mal) => {
      // lo que pide la persona pasa delante de la precarga
      this.cola[alFondo ? "push" : "unshift"]({ a: { ...args, tipo, id: this.sigId++ }, ok, mal });
      this.bombear();
    });
  },
  bombear() {
    if (this.enCurso || !this.cola.length) return;
    this.enCurso = this.cola.shift();
    this.enviar("accion", this.enCurso.a);
  },
  recibir(salidas) {
    for (const r of salidas ?? []) {
      if (r.id !== this.enCurso?.a.id) continue;
      const { ok, mal } = this.enCurso;
      this.enCurso = null;
      if (r.error) mal(new Error(r.error)); else ok(r.datos);
    }
    this.bombear();
  },

  // Seccion ya armada en el servidor. Si esta vigente se usa y punto; si no,
  // se muestra la que hay y se trae la nueva por detras.
  async seccion(nombre) {
    const hay = this.secciones[nombre];
    if (hay && Date.now() - hay.visto < VIGENCIA_MS) return hay.datos;
    if (hay) { this.traer(nombre); return hay.datos; }
    return this.traer(nombre);
  },
  async traer(nombre, alFondo = false) {
    for (;;) {
      const r = await this.pedir("seccion", { nombre }, alFondo);
      if (r.error) throw new Error(r.error);
      if (!r.espera) {
        const antes = this.secciones[nombre];
        this.fuera = new Set(r.fuera);
        this.bandeja = { ...r.bandeja, ...this.pendientes };  // lo marcado recien gana a lo que aun no guardo GitHub
        if (!this.siguiendo) this.seguidos = new Set(r.seguidos);
        this.secciones[nombre] = { datos: r.datos, v: r.v, visto: Date.now() };
        if (antes && antes.v !== r.v && this.ruta === nombre) VISTAS[nombre]?.nuevos?.(r.datos);
        return r.datos;
      }
      await new Promise((f) => setTimeout(f, 2000));
    }
  },

  f(vista, inicial) {
    if (!this.filtros[vista]) {
      const memo = JSON.parse(sessionStorage.getItem(`vali:${vista}`) || "null");
      this.filtros[vista] = { ...inicial, ...memo };
    }
    return this.filtros[vista];
  },
  recordar(vista, sinGuardar = []) {
    const copia = { ...this.filtros[vista] };
    sinGuardar.forEach((k) => delete copia[k]);
    sessionStorage.setItem(`vali:${vista}`, JSON.stringify(copia));
  },

  // Acepta la ruta base de una seccion por pais y elige el pais vigente
  resolver(ruta) {
    if (VISTAS[ruta]) return ruta;
    const p = (this.pais || "PE").toLowerCase();
    return VISTAS[`${ruta}_${p}`] ? `${ruta}_${p}` : "panel";
  },
  ir(ruta) {
    ruta = this.resolver(ruta);
    if (location.hash.slice(1) !== ruta) history.pushState(null, "", `#${ruta}`);
    this.pintarRuta(ruta);
  },
  // Sin animacion de entrada: se cambia de seccion decenas de veces al dia
  async pintarRuta(ruta) {
    const v = VISTAS[ruta];
    this.ruta = ruta;
    this.cerrarDetalle();
    this.raiz.querySelectorAll("[data-ir]").forEach((b) => {
      const es = b.dataset.ir === base(ruta);
      b.classList.toggle("activo", es);
      if (es) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    selectorPais();
    const main = this.$(".main");
    main.scrollTop = 0;
    main.innerHTML = `<header class="top"><div class="titulo"><h1>${esc(v.titulo)}</h1><p class="sub">${esc(v.sub ?? "")}</p></div><div class="ctrl"></div></header><div class="cuerpo"></div>`;
    const cuerpo = main.querySelector(".cuerpo");
    try {
      await v.abrir(cuerpo, main.querySelector(".ctrl"));
    } catch (e) {
      if (this.ruta === ruta) cuerpo.innerHTML = `<div class="aviso">No se pudo cargar esta sección. ${esc(e.message)}</div>`;
    }
    this.ajustar();
  },
  ajustar() {
    const top = this.$(".top");
    if (top) this.raiz.style.setProperty("--alto-top", `${top.offsetHeight}px`);
    this.raiz.querySelectorAll(".seg").forEach(moverSeg);
  },

  // Detalle lateral
  detalle(html) {
    const det = this.$(".det");
    det.innerHTML = `<button type="button" class="cerrar" aria-label="Cerrar">×</button>${html}`;
    det.classList.add("abierto");
    det.scrollTop = 0;
    return det;
  },
  cerrarDetalle() {
    this.$(".det")?.classList.remove("abierto");
    this.alCerrar?.();
    this.alCerrar = null;
  },

  aviso(texto, deshacer) {
    const t = this.$(".toast");
    t.innerHTML = `<span>${esc(texto)}</span>${deshacer ? `<button type="button">Deshacer</button>` : ""}`;
    t.classList.add("ver");
    clearTimeout(this.toastT);
    this.toastT = setTimeout(() => t.classList.remove("ver"), deshacer ? 8000 : 2600);
    if (deshacer) t.querySelector("button").onclick = () => { deshacer(); t.classList.remove("ver"); };
  },
  fallo(e) { this.aviso(`No se pudo: ${e.message}`); },

  // Enviar material al chat de redaccion
  armar(items, cliente, porQue) {
    this.semilla = { cliente, items, por_que: porQue ?? null };
    this.ir("alertas");
  },
};

const espera = (n = 5) => '<div class="esq"></div>'.repeat(n);

function moverSeg(caja) {
  const b = caja.querySelector('[aria-pressed="true"]');
  const pill = caja.querySelector("i");
  if (!b || !pill) return;
  pill.style.width = `${b.offsetWidth}px`;
  pill.style.transform = `translateX(${b.offsetLeft}px)`;
}

function segmentado(caja, opciones, valor, alCambiar) {
  caja.classList.add("seg");
  caja.innerHTML = opciones.map((o) => `<button type="button" aria-pressed="${o === valor}">${esc(o)}</button>`).join("") + "<i></i>";
  caja.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    caja.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    moverSeg(caja);
    alCambiar(b.textContent);
  };
  requestAnimationFrame(() => moverSeg(caja));
}

function botonesCliente(caja, lista, valor, alCambiar, conTodos = true) {
  const TODOS = "Todos los clientes";
  const slug = new Map(lista.map((c) => [App.nombre(c), c]));
  segmentado(caja, [...(conTodos ? [TODOS] : []), ...slug.keys()], valor ? App.nombre(valor) : conTodos ? TODOS : null,
    (t) => alCambiar(slug.get(t) ?? ""));
}

function pestanas(caja, opciones, valor, alCambiar) {
  // se reusa: rehacerla cortaria el deslizamiento de la linea
  if (caja.children.length !== opciones.length + 1) {
    caja.innerHTML = opciones.map(([k]) => `<button type="button" role="tab" data-tab="${esc(k)}"></button>`).join("") + "<i></i>";
    caja.onclick = (e) => { const b = e.target.closest("[data-tab]"); if (b) caja.alCambiar(b.dataset.tab); };
  }
  caja.alCambiar = alCambiar;
  opciones.forEach(([k, t], i) => {
    caja.children[i].textContent = t;
    caja.children[i].setAttribute("aria-selected", k === valor);
  });
  const b = caja.querySelector('[aria-selected="true"]');
  const linea = caja.lastElementChild;
  requestAnimationFrame(() => { linea.style.transform = `translateX(${b.offsetLeft}px) scaleX(${b.offsetWidth})`; });
}

function cifra(el, hasta) {
  const desde = Number(el.dataset.n ?? hasta);
  el.dataset.n = hasta;
  if (typeof hasta !== "number" || desde === hasta || quieto()) { el.textContent = typeof hasta === "number" ? miles(hasta) : hasta; return; }
  const t0 = performance.now();
  const paso = (t) => {
    if (Number(el.dataset.n) !== hasta) return;
    const k = Math.min((t - t0) / 240, 1);
    el.textContent = miles(Math.round(desde + (hasta - desde) * (1 - (1 - k) ** 3)));
    if (k < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

function kpis(caja, datos) {
  if (caja.children.length !== datos.length) {
    caja.innerHTML = datos.map(() => "<div class=kpi><b></b><span></span><small></small></div>").join("");
    caja.style.setProperty("--n", datos.length);
  }
  datos.forEach(([n, t, x], i) => {
    const k = caja.children[i];
    cifra(k.querySelector("b"), n);
    k.querySelector("span").textContent = t;
    k.querySelector("small").textContent = x ?? "";
  });
}

function entrar(lista) {
  if (quieto()) return;
  [...lista].slice(0, 8).forEach((el, i) => el.animate(
    [{ opacity: 0, transform: "translateY(5px)" }, { opacity: 1, transform: "none" }],
    { duration: 180, delay: i * 18, easing: "cubic-bezier(.23,1,.32,1)", fill: "backwards" }));
}

// Barra de filtros. defs: {k, t, tipo: "select"|"texto"|"fecha"|"check", ops}.
function campoFiltro(d, f) {
  if (d.tipo === "texto") return `<input class="buscar" type="search" data-f="${d.k}" placeholder="${esc(d.t)}" aria-label="${esc(d.t)}" value="${esc(f[d.k] ?? "")}">`;
  if (d.tipo === "fecha") return `<label class="campo">${esc(d.t)}<input type="date" data-f="${d.k}" value="${esc(f[d.k] ?? "")}"></label>`;
  if (d.tipo === "check") return `<label class="check"><input type="checkbox" data-f="${d.k}"${f[d.k] ? " checked" : ""}>${esc(d.t)}</label>`;
  return `<select data-f="${d.k}" aria-label="${esc(d.t)}"><option value="">${esc(d.todos ?? d.t)}</option>${(d.ops ?? []).map((o) => {
    const [v, t] = Array.isArray(o) ? o : [o, o];
    return `<option value="${esc(v)}"${String(v) === String(f[d.k] ?? "") ? " selected" : ""}>${esc(t)}</option>`;
  }).join("")}</select>`;
}

function escucharFiltros(caja, f, alCambiar) {
  const leer = (e) => {
    const el = e.target.closest("[data-f]");
    if (!el) return;
    f[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value;
    alCambiar(el.dataset.f);
  };
  caja.oninput = leer;  // una sola: las pestanas reusan la caja
}

// Tabla ordenable. cols: {k, t, f(fila)->html, ord: valor para ordenar, ancho}.
function tabla(caja, { cols, filas, orden, alOrdenar, clic, vacio, activa }) {
  const [col, dir] = orden ?? [];
  const def = cols.find((c) => c.k === col);
  const vista = def ? [...filas].sort((a, b) => {
    const va = def.ord ? def.ord(a) : a[col];
    const vb = def.ord ? def.ord(b) : b[col];
    if (va === null || va === undefined || va === "") return 1;
    if (vb === null || vb === undefined || vb === "") return -1;
    return dir * String(va).localeCompare(String(vb), "es", { numeric: true });
  }) : filas;
  if (!vista.length) { caja.innerHTML = `<div class="vacio">${esc(vacio ?? "Nada con estos filtros.")}</div>`; return; }
  const tope = caja.tope ?? PASO;
  caja.innerHTML = `<div class="tabla"><table><thead><tr>${cols.map((c) => `<th data-col="${c.k}"${c.ancho ? ` style="width:${c.ancho}"` : ""}${c.k === col ? ` aria-sort="${dir > 0 ? "ascending" : "descending"}"` : ""}>${esc(c.t)}${c.k === col ? (dir > 0 ? " ↑" : " ↓") : ""}</th>`).join("")}</tr></thead>
    <tbody>${vista.slice(0, tope).map((p, i) => `<tr data-i="${i}"${clic ? ' class="clic" tabindex="0"' : ""}${activa?.(p) ? ' aria-selected="true"' : ""}>${cols.map((c) => `<td>${c.f ? c.f(p) : esc(p[c.k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    ${vista.length > tope ? `<button type="button" class="mas">Ver ${miles(Math.min(vista.length - tope, PASO))} más de ${miles(vista.length - tope)}</button>` : ""}`;
  caja.onclick = (e) => {
    if (e.target.closest("a")) return;
    const th = e.target.closest("[data-col]");
    if (th) { alOrdenar?.([th.dataset.col, col === th.dataset.col ? -dir : 1]); return; }
    if (e.target.closest(".mas")) { caja.tope = tope + PASO; tabla(caja, { cols, filas, orden, alOrdenar, clic, vacio, activa }); return; }
    const tr = e.target.closest("tr[data-i]");
    if (tr && clic) { caja.querySelectorAll("tr[aria-selected]").forEach((x) => x.removeAttribute("aria-selected")); tr.setAttribute("aria-selected", "true"); clic(vista[tr.dataset.i]); }
  };
}

// Bloque de acciones que se repite en cada detalle.
function bloqueArmar(items, sugerido, porQue, clientes) {
  const lista = clientes ?? Object.keys(App.d.clientes);
  return `<div class="d-cli" data-lista="${esc(lista.join(","))}" data-sug="${esc(sugerido ?? "")}"></div>
    <button type="button" class="btn d-armar">Armar alerta</button>
    <button type="button" class="btn d-copiar">Copiar pedido para Claude</button>`;
}

function conectarArmar(det, items, porQue) {
  const armar = det.querySelector(".d-armar");
  const caja = det.querySelector(".d-cli");
  let cli = caja.dataset.sug;
  const estado = () => {
    armar.disabled = !cli;
    armar.textContent = cli ? `Armar alerta para ${App.nombre(cli)}` : "Elige el cliente";
  };
  botonesCliente(caja, caja.dataset.lista.split(","), cli, (v) => { cli = v; estado(); }, false);
  estado();
  armar.onclick = () => App.armar(items, cli, typeof porQue === "function" ? porQue(cli) : porQue);
  det.querySelector(".d-copiar").onclick = async () => {
    const para = cli ? App.nombre(cli) : "el cliente";
    await navigator.clipboard.writeText(`/alerta ${items[0].titulo} para ${para} ${items[0].url ?? ""}`.trim());
    App.aviso("Pedido copiado");
  };
}

function item(titulo, url, resumen, pais, fuente, fecha, tipo = "noticia") {
  return { titulo, url, resumen, pais, fuente, fecha: (fecha || "").slice(0, 10) || null, tipo };
}

// Grafico de lineas de dos series, sin dependencias.
function evolucion(datos, an = 640, al = 150) {
  if (!datos?.length) return "";
  const m = 26;
  const tope = Math.max(...datos.flatMap((d) => [d.presentados, d.leyes]), 1);
  const x = (i) => (datos.length === 1 ? an / 2 : m + (i * (an - 2 * m)) / (datos.length - 1));
  const y = (v) => al - 22 - (v / tope) * (al - 40);
  const linea = (k, color) => `<polyline fill="none" stroke="${color}" stroke-width="2" points="${datos.map((d, i) => `${x(i)},${y(d[k])}`).join(" ")}"/>`
    + datos.map((d, i) => `<circle cx="${x(i)}" cy="${y(d[k])}" r="3.5" fill="${color}"><title>${esc(d.mes)}: ${d[k]}</title></circle>
      ${k === "leyes" && !d[k] ? "" : `<text x="${x(i)}" y="${y(d[k]) - 8}" text-anchor="middle" class="eti">${d[k]}</text>`}`).join("");
  return `<div class="graf"><div class="ley"><span class="s1">Presentados</span><span class="s2">Leyes publicadas</span></div>
    <svg viewBox="0 0 ${an} ${al}" role="img" aria-label="Evolución mensual de proyectos">
    ${datos.map((d, i) => `<text x="${x(i)}" y="${al - 4}" text-anchor="middle" class="eti">${d.mes.split("-").reverse().join("/")}</text>`).join("")}
    ${linea("presentados", "#0A294D")}${linea("leyes", "#9C7A2E")}</svg></div>`;
}

// Transcripcion con resumen: la usan las dos agendas y TV.
function fichaTranscripcion(t, urlVideo) {
  const dur = t.dur ? `${Math.floor(t.dur / 3600)} h ${Math.floor((t.dur % 3600) / 60)} min` : "";
  return `<h2>${esc(t.titulo)}</h2>
    <div class="marcas">${[t.camara, t.tipo, fechaCorta(t.fecha), dur].filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join("")}</div>
    ${t.temas?.length ? `<div class="marcas">${t.temas.map((x) => `<span class="cli">${esc(x)}</span>`).join("")}</div>` : ""}
    ${t.resumen ? `<p>${esc(t.resumen)}</p>` : `<p class="nota">Resumen pendiente de generar.</p>`}
    ${t.ideas?.length ? `<ul>${t.ideas.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    ${t.cumplida ? `<p class="nota">Agenda: ${esc(t.cumplida)}</p>` : ""}
    <div class="acciones">${enlace(urlVideo, "Ver el video", "btn pri")}
      <button type="button" class="btn d-texto">Ver transcripción completa</button>
      <div class="texto" hidden></div>
      <div class="qa"></div>
      <form class="linea d-preg"><input class="buscar" placeholder="Pregúntale a la transcripción" aria-label="Pregunta sobre la transcripción"><button class="btn">Preguntar</button></form>
    </div>`;
}

function conectarTranscripcion(det, t) {
  det.querySelector(".d-texto").onclick = () => verTexto(det, t.video_id, t.titulo);
  const qa = det.querySelector(".qa");
  det.querySelector(".d-preg").onsubmit = async (e) => {
    e.preventDefault();
    const input = e.target.querySelector("input");
    const pregunta = input.value.trim();
    if (!pregunta) return;
    input.value = "";
    qa.insertAdjacentHTML("beforeend", `<p class="q">${esc(pregunta)}</p><p class="r pensando">Pensando…</p>`);
    const r = qa.lastElementChild;
    try {
      r.textContent = await App.pedir("preguntar_sesion", { video_id: t.video_id, titulo: t.titulo, pregunta });
    } catch (err) { r.textContent = `No se pudo responder: ${err.message}`; }
    r.classList.remove("pensando");
  };
}

async function verTexto(det, videoId, titulo) {
  const caja = det.querySelector(".texto");
  caja.hidden = !caja.hidden;
  if (caja.hidden || caja.dataset.listo) return;
  caja.textContent = "Abriendo…";
  try {
    const texto = await App.pedir("texto", { video_id: videoId });
    caja.dataset.listo = 1;
    caja.innerHTML = `<div class="linea"><button type="button" class="btn t-copiar">Copiar</button><a class="btn t-bajar" download="${esc(titulo).slice(0, 60)}.txt">Descargar</a></div><pre></pre>`;
    caja.querySelector("pre").textContent = texto || "Sin texto guardado.";
    caja.querySelector(".t-bajar").href = URL.createObjectURL(new Blob([`${titulo}\n\n${texto}`], { type: "text/plain" }));
    caja.querySelector(".t-copiar").onclick = async () => { await navigator.clipboard.writeText(texto); App.aviso("Transcripción copiada"); };
  } catch (e) { caja.textContent = `No se pudo abrir: ${e.message}`; }
}

function montar(raiz) {
  App.raiz = raiz;
  raiz.innerHTML = `<nav class="rail" aria-label="Menú"></nav><main class="main"></main>
    <aside class="det" aria-label="Detalle"></aside><div class="toast" role="status"></div>`;
  raiz.addEventListener("click", (e) => {
    const t = e.target;
    const ir = t.closest("[data-ir]");
    if (ir) return App.ir(ir.dataset.ir);
    if (t.closest(".salir")) return App.enviar("accion", { tipo: "salir", id: 0 });
    if (t.closest(".cerrar")) return App.cerrarDetalle();
  });
  const teclas = (e) => {
    if (!raiz.isConnected) return document.removeEventListener("keydown", teclas);
    if (e.key === "Escape") return App.cerrarDetalle();
    if (/INPUT|SELECT|TEXTAREA/.test(e.composedPath()[0].tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); raiz.querySelector(".main .buscar")?.focus(); return; }
    VISTAS[App.ruta]?.tecla?.(e);
  };
  document.addEventListener("keydown", teclas);
  addEventListener("resize", () => App.ajustar());
  addEventListener("popstate", () => App.pintarRuta(App.resolver(location.hash.slice(1))));
}

function menu() {
  const d = App.d;
  App.$(".rail").innerHTML = `<div class="marca"><i class="logo" aria-hidden="true"></i><div>Vali Intelligence<small>Radar Legislativo</small></div></div><div class="r-pais"><div></div></div>`
    + d.menu.map(([g, items]) => (g ? `<div class="grupo">${esc(g)}</div>` : "")
      + items.map(([t, r, ic]) => `<button type="button" class="ir" data-ir="${esc(r)}">${icono(ic)}${esc(t)}</button>`).join("")).join("")
    + (d.usuario ? `<div class="pie">${esc(d.usuario)}<button type="button" class="salir">Cerrar sesión</button></div>` : "");
}

// Un solo pais para toda la app. Las secciones por pais cambian de ruta; las demas se repintan.
function selectorPais() {
  const nombres = { "": "Ambos", PE: "Perú", EC: "Ecuador" };
  const p = paisDeRuta(App.ruta);
  const ops = p ? ["Perú", "Ecuador"] : Object.values(nombres);  // proyectos, agenda y noticias son de un pais
  segmentado(App.$(".r-pais > div"), ops, nombres[p || App.pais], (t) => {
    App.pais = Object.keys(nombres).find((k) => nombres[k] === t);
    localStorage.setItem("vali:pais", App.pais);
    App.ir(paisDeRuta(App.ruta) ? base(App.ruta) : App.ruta);
  });
}

// Deja listas las demas secciones sin estorbar: una a la vez y solo con el navegador libre.
function precargar() {
  const faltan = Object.keys(VISTAS).filter((v) => VISTAS[v].seccion && !App.secciones[VISTAS[v].seccion]);
  if (!faltan.length) return;
  (window.requestIdleCallback ?? setTimeout)(async () => {
    try { await App.traer(VISTAS[faltan[0]].seccion, true); precargar(); } catch { /* se reintenta al abrirla */ }
  });
}

export default function ({ data, parentElement, setTriggerValue }) {
  const raiz = parentElement.querySelector(".app");
  App.enviar = setTriggerValue;
  if (!App.raiz || !App.raiz.isConnected) {
    App.d = data;
    montar(raiz);
    menu();
    App.pintarRuta(App.resolver(location.hash.slice(1))).then(precargar);
  }
  App.recibir(data?.salidas);
  return undefined;
}
