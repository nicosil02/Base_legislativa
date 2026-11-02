// Redactar alertas, Buscar en todo y Resumen para clientes.
const negrita = (t) => esc(t).replace(/\*([^*\n]+?)\*/g, "<b>$1</b>");

VISTAS.alertas = (() => {
  // El chat vive en el navegador: seguir pidiendo ajustes no depende del servidor.
  const c = { cliente: "", historia: [], material: null, borrador: null, ocupado: false };
  let raiz;
  const FALLO = "No se pudo conectar con Gemini: ";
  const validos = () => c.historia.filter(([r, t]) => r === "user" || !t.startsWith(FALLO));
  const respuestas = () => validos().filter(([r]) => r === "assistant");

  function mensajes() {
    const caja = raiz.querySelector(".chat");
    // el primer mensaje con material es el prompt interno, no algo que se escribio
    caja.innerHTML = c.historia.slice(c.material?.items?.length && !c.borrador ? 1 : 0).map(([r, t]) => `<div class="msg ${r}">${negrita(t).replace(/\n/g, "<br>")}</div>`).join("")
      + (c.ocupado ? `<div class="msg assistant pensando">${esc(c.ocupado)}</div>` : "");
    const ult = caja.lastElementChild;
    if (ult && !quieto()) ult.animate([{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { duration: 200, easing: "cubic-bezier(.23,1,.32,1)" });
    App.$(".main").scrollTop = App.$(".main").scrollHeight;
    guardar();
  }

  function guardar() {
    const caja = raiz.querySelector(".final");
    const ult = respuestas().at(-1);
    caja.hidden = !ult;
    raiz.querySelector(".r-nueva").hidden = !c.historia.length;
    if (!ult) return;
    const p = c.material?.items?.[0] ?? {};
    caja.innerHTML = `<h2>Guardar como enviada</h2>
      <label class="campo">Texto final<textarea class="g-texto" rows="9">${esc(ult[1])}</textarea></label>
      <div class="barra"><input class="buscar g-titulo" placeholder="Título para el historial" aria-label="Título" value="${esc(p.titulo ?? "")}">
        <select class="g-pais" aria-label="País">${["Perú", "Ecuador", "Regional"].map((x) => `<option${x === (PAISES[p.pais] ?? "Perú") ? " selected" : ""}>${x}</option>`).join("")}</select>
        <input class="buscar g-linea" placeholder="Línea, opcional" aria-label="Línea"></div>
      <input class="buscar g-url" placeholder="Fuente" aria-label="Fuente" value="${esc(p.url ?? "")}">
      <p class="nota">Vista previa con la negrita de WhatsApp</p><div class="previa"></div>
      <div class="linea"><button type="button" class="btn g-copiar">Copiar</button><button type="button" class="btn pri g-guardar">Guardar en el historial de ${esc(App.nombre(c.cliente))}</button></div>`;
    const texto = caja.querySelector(".g-texto");
    const previa = () => { caja.querySelector(".previa").innerHTML = negrita(texto.value); };
    texto.oninput = previa;
    previa();
    caja.querySelector(".g-copiar").onclick = async () => { await navigator.clipboard.writeText(texto.value); App.aviso("Texto copiado"); };
    caja.querySelector(".g-guardar").onclick = async (e) => {
      const titulo = caja.querySelector(".g-titulo").value.trim();
      if (!texto.value.trim() || !titulo) return App.aviso("Falta el texto o el título");
      e.target.disabled = true;
      try {
        await App.pedir("guardar_alerta", { cliente: c.cliente, titulo, texto: texto.value, pais: caja.querySelector(".g-pais").value,
                                            url: caja.querySelector(".g-url").value, linea: caja.querySelector(".g-linea").value, borrador: c.borrador });
        c.borrador = null;
        App.aviso(`Guardada en el historial de ${App.nombre(c.cliente)}`);
        borradores();
      } catch (err) { App.fallo(err); }
      e.target.disabled = false;
    };
  }

  function material() {
    const caja = raiz.querySelector(".material");
    const m = c.material;
    caja.innerHTML = m ? m.items.map((it) => `<div class="fila noticia"><div class="marcas">${[it.fuente, it.fecha, it.pais].filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join("")}</div><h3>${enlace(it.url, it.titulo) || esc(it.titulo)}</h3></div>`).join("")
      + (m.por_que ? `<p class="nota">Por qué le interesaría: ${esc(m.por_que)}</p>` : "") : "";
  }

  async function borradores() {
    const caja = raiz.querySelector(".borr");
    try {
      const lista = (await App.pedir("borradores")).filter((b) => b.cliente === c.cliente);
      caja.innerHTML = lista.map((b) => `<details><summary>Borrador listo: ${esc(b.titulo)} ${esc(b.fecha ?? "")}</summary><div class="previa">${negrita(b.texto)}</div>
        ${b.sustento ? `<p class="nota">${esc(b.sustento)}</p>` : ""}<div class="linea"><button type="button" class="btn pri" data-usar="${esc(b.id)}">Usar este borrador</button><button type="button" class="btn" data-fuera="${esc(b.id)}">Descartar</button></div></details>`).join("");
      caja.onclick = async (e) => {
        const usar = e.target.closest("[data-usar]"), fuera = e.target.closest("[data-fuera]");
        if (usar) {
          const b = lista.find((x) => x.id === usar.dataset.usar);
          c.material = { cliente: c.cliente, items: [{ titulo: b.titulo, url: b.url, pais: b.pais }] };
          c.historia = [["user", `Borrador preparado para ${c.cliente}. Sustento:\n${b.sustento ?? ""}`], ["assistant", b.texto]];
          c.borrador = b.id;
          material(); mensajes();
        }
        if (fuera) { try { await App.pedir("borrador_fuera", { id: fuera.dataset.fuera }); borradores(); } catch (err) { App.fallo(err); } }
      };
    } catch (e) { caja.innerHTML = `<p class="nota">No se pudieron traer los borradores: ${esc(e.message)}</p>`; }
  }

  async function enviar(prompt) {
    c.historia.push(["user", prompt]);
    c.ocupado = "Redactando…";
    mensajes();
    try {
      const r = await App.pedir("chat", { cliente: c.cliente, historia: validos().slice(0, -1), prompt });
      c.historia.push(["assistant", r.respuesta]);
    } catch (e) { c.historia.push(["assistant", FALLO + e.message]); }
    c.ocupado = false;
    if (raiz?.isConnected) mensajes();
  }

  async function iniciar(semilla) {
    Object.assign(c, { cliente: semilla.cliente, historia: [], material: semilla, borrador: null, ocupado: "Buscando contexto y redactando…" });
    material(); mensajes();
    try {
      const r = await App.pedir("chat_inicio", { cliente: c.cliente, material: semilla });
      c.historia.push(["user", r.prompt], ["assistant", r.error ? `${FALLO}${r.error}. Escribe "sigue" para reintentar.` : r.respuesta]);
    } catch (e) { c.historia.push(["user", ""], ["assistant", FALLO + e.message]); }
    c.ocupado = false;
    if (raiz?.isConnected) mensajes();
  }

  return {
    titulo: "Redactar alertas", sub: "Con el bluebook del cliente y sus alertas anteriores. No envía nada a ningún cliente.",
    async abrir(cuerpo, ctrl) {
      raiz = cuerpo;
      const lista = Object.keys(App.d.clientes);
      const semilla = App.semilla;
      App.semilla = null;
      if (semilla) c.cliente = semilla.cliente;
      c.cliente ||= lista[0];
      ctrl.innerHTML = `<div class="r-cli"></div>`;
      cuerpo.innerHTML = `<div class="redaccion"><div class="borr"></div><div class="material"></div><div class="chat" aria-live="polite"></div>
        <form class="enviar"><textarea rows="2" aria-label="Mensaje" placeholder="Pega lo que quieras o pide un ajuste. Enter envía."></textarea><button class="btn pri">Enviar</button></form>
        <button type="button" class="btn r-nueva" hidden>Nueva conversación</button><div class="final" hidden></div></div>`;
      const form = cuerpo.querySelector(".enviar");
      const area = form.querySelector("textarea");
      form.onsubmit = (e) => { e.preventDefault(); const t = area.value.trim(); if (t && !c.ocupado) { area.value = ""; enviar(t); } };
      area.onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } };
      botonesCliente(ctrl.querySelector(".r-cli"), lista, c.cliente, (v) => {
        Object.assign(c, { cliente: v, historia: [], material: null, borrador: null });
        material(); mensajes(); borradores();
      }, false);
      cuerpo.querySelector(".r-nueva").onclick = () => { Object.assign(c, { historia: [], material: null, borrador: null }); material(); mensajes(); };
      if (semilla) iniciar(semilla); else { material(); mensajes(); }
      borradores();
    },
  };
})();

VISTAS.buscar = (() => {
  const ETIQUETA = { pl: "Proyecto de ley", noticia: "Noticia", sesion: "Sesión", alerta: "Alerta enviada" };
  return {
    titulo: "Buscar en todo", sub: "Proyectos, noticias y sesiones de Perú y Ecuador. Escribe una idea, no palabras exactas.",
    async abrir(cuerpo) {
      const f = App.f("buscar", { q: "", pais: "", tipo_doc: "", k: "15" });
      cuerpo.innerHTML = `<form class="barra filtros b-form">${campoFiltro({ k: "q", t: "Ej.: regulación de plaguicidas, biometría, PL 565 (tecla /)", tipo: "texto" }, f)}
        ${campoFiltro({ k: "pais", t: "País", todos: "Ambos países", ops: Object.entries(PAISES) }, f)}
        ${campoFiltro({ k: "tipo_doc", t: "Tipo", todos: "Todo tipo", ops: Object.entries({ pl: "Proyectos de ley", noticia: "Noticias", sesion: "Sesiones", alerta: "Alertas enviadas" }) }, f)}
        <select data-f="k" aria-label="Resultados">${["15", "30", "60"].map((n) => `<option${n === f.k ? " selected" : ""}>${n}</option>`).join("")}</select>
        <button class="btn pri">Buscar</button></form>
        <p class="b-cuenta nota"></p><div class="b-res"></div>
        <section class="pregunta"><h2>Preguntarle al cerebro</h2><p class="nota">Cruza proyectos, sesiones, noticias y lo que le importa a cada cliente, y cita en qué se basa. Sabe hasta ayer; para lo de hoy usa el Panel.</p>
        <form class="enviar p-form"><textarea rows="2" aria-label="Pregunta" placeholder="¿Qué se discutió esta semana sobre agroquímicos que le importe a Bayer?"></textarea><button class="btn pri">Preguntar</button></form><div class="p-res"></div></section>`;
      escucharFiltros(cuerpo.querySelector(".b-form"), f, () => App.recordar("buscar"));
      App.pedir("total_cerebro").then((n) => { const c = cuerpo.querySelector(".b-cuenta"); if (c && n != null) c.textContent = `${miles(n)} documentos en el cerebro.`; }).catch(() => {});
      const res = cuerpo.querySelector(".b-res");
      cuerpo.querySelector(".b-form").onsubmit = async (e) => {
        e.preventDefault();
        if (!f.q?.trim()) return;
        res.innerHTML = espera(4);
        try {
          const filas = await App.pedir("buscar", { q: f.q.trim(), k: f.k, tipo_doc: f.tipo_doc, pais: f.pais });
          res.innerHTML = filas.length ? filas.map((r) => `<article class="fila noticia"><div class="marcas"><span>${esc(ETIQUETA[r.tipo] ?? r.tipo)}</span><span>${esc(r.pais)}</span><span>${esc(fechaCorta(r.fecha) || "sin fecha")}</span></div>
            <h3>${enlace(r.url, r.titulo || "Sin título") || esc(r.titulo || "Sin título")}</h3><small>${esc(r.detalle.join(", "))}</small></article>`).join("") : `<div class="vacio">Sin resultados. Prueba con otra idea.</div>`;
          entrar(res.querySelectorAll(".fila"));
        } catch (err) { res.innerHTML = `<div class="aviso">No se pudo buscar: ${esc(err.message)}</div>`; }
      };
      const pres = cuerpo.querySelector(".p-res");
      const pf = cuerpo.querySelector(".p-form");
      pf.querySelector("textarea").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); pf.requestSubmit(); } };
      pf.onsubmit = async (e) => {
        e.preventDefault();
        const pregunta = pf.querySelector("textarea").value.trim();
        if (!pregunta) return;
        pres.innerHTML = `<div class="msg assistant pensando">Pensando…</div>`;
        try { pres.innerHTML = `<div class="previa">${negrita(await App.pedir("preguntar_cerebro", { pregunta }))}</div>`; } catch (err) { pres.innerHTML = `<div class="aviso">No se pudo responder: ${esc(err.message)}</div>`; }
      };
    },
  };
})();

VISTAS.resumen = (() => {
  let hecho = null;
  const pintar = (caja, r) => {
    caja.innerHTML = r.nota ? `<div class="vacio">${esc(r.nota)}</div>`
      : `<p class="nota">${r.cuenta ? `Armado a las ${esc(r.fecha)} en Lima con ${Object.entries(r.cuenta).map(([k, v]) => `${v} ${esc(k)}`).join(", ")}` : `Último resumen enviado por Telegram, ${esc(fechaCorta(r.fecha))}`}</p>
         <div class="resumen">${negrita(r.texto.replace(/\*\*/g, "*"))}</div>`;
  };
  return {
    titulo: "Resumen para clientes", sub: "Lo de las últimas 24 horas que le importa a cada cliente, con el porqué y el enlace",
    async abrir(cuerpo, ctrl) {
      ctrl.innerHTML = `<button type="button" class="btn pri r-armar">Armar ahora con lo último</button>`;
      cuerpo.innerHTML = `<div class="r-caja">${espera(3)}</div>`;
      const caja = cuerpo.querySelector(".r-caja");
      const boton = ctrl.querySelector(".r-armar");
      boton.onclick = async () => {
        boton.disabled = true;
        caja.innerHTML = `<div class="msg assistant pensando">Juntando lo de las últimas 24 horas y escribiendo el resumen, puede tardar 1 minuto.</div>`;
        try { hecho = await App.pedir("resumen_nuevo"); pintar(caja, hecho); } catch (e) { caja.innerHTML = `<div class="aviso">No se pudo armar el resumen: ${esc(e.message)}</div>`; }
        boton.disabled = false;
      };
      pintar(caja, hecho ?? await App.pedir("resumen"));
    },
  };
})();
