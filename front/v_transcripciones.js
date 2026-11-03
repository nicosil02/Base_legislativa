// Transcripciones de sesiones de Peru y Ecuador, en tarjetas con filtros al costado.
VISTAS.transcripciones = (() => {
  const NOM = "transcripciones";
  const TOPE = 30;
  const RUIDO = "Coyuntura política";  // casi todas la llevan: no distingue nada
  let d, raiz, vivos = [], reloj, tope = TOPE;
  const s = () => App.f(NOM, { q: "", organo: "", camara: "", tema: "", ini: "", fin: "", vivo: false });

  const sinTilde = (t) => String(t ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const codigo = () => App.pais;
  const dur = (seg) => (seg ? (seg >= 3600 ? `${Math.floor(seg / 3600)} h ${Math.floor((seg % 3600) / 60)} min` : `${Math.round(seg / 60)} min`) : "");
  const temas = (t) => (t.temas ?? []).filter((x) => x !== RUIDO);
  const enVivo = (t) => vivos.some((v) => v.id === t.video_id);

  function filtradas() {
    const f = s();
    const p = codigo(f.pais);
    const q = sinTilde(f.q).split(/\s+/).filter(Boolean);
    return d.filas.filter((t) => (!p || t.pais === p) && (!f.organo || t.organo === f.organo) && (!f.camara || t.camara === f.camara)
      && (!f.tema || t.temas?.includes(f.tema)) && (!f.ini || (t.fecha ?? "") >= f.ini) && (!f.fin || (t.fecha ?? "") <= f.fin)
      && (!f.vivo || enVivo(t))
      && (!q.length || q.every((w) => sinTilde(`${t.organo} ${t.titulo} ${t.resumen ?? ""} ${(t.ideas ?? []).join(" ")}`).includes(w))));
  }

  // Sesiones en vivo que todavia no estan en la base: van arriba como tarjeta propia.
  function soloVivos() {
    const f = s();
    const p = codigo(f.pais);
    const ids = new Set(d.filas.map((t) => t.video_id));
    return vivos.filter((v) => !ids.has(v.id) && (!p || v.pais === p));
  }

  function tarjeta(t, i) {
    const vivo = enVivo(t);
    const marcas = [PAISES[t.pais], t.camara && t.camara !== "Sin confirmar" ? t.camara : null, fechaCorta(t.fecha), dur(t.dur)].filter(Boolean);
    return `<button type="button" class="tarjeta${vivo ? " viva" : ""}" data-i="${i}">
      <span class="t-cab">${vivo ? `<span class="envivo"><span class="punto"></span>En vivo</span>` : ""}<span class="t-org">${esc(t.organo)}</span></span>
      <span class="t-tit">${esc(oracion(t.titulo))}</span>
      <span class="marcas">${marcas.map((x) => `<span>${esc(x)}</span>`).join("")}</span>
      <span class="t-res">${esc(t.resumen ?? "Resumen pendiente de generar.")}</span>
      ${temas(t).length ? `<span class="t-temas">${temas(t).map((x) => `<span>${esc(x)}</span>`).join("")}</span>` : ""}
      <span class="t-ver">Ver transcripción</span></button>`;
  }

  function tarjetaVivo(v) {
    return `<a class="tarjeta viva" href="${web(v.url) ?? "#"}" target="_blank" rel="noopener">
      <span class="t-cab"><span class="envivo"><span class="punto"></span>En vivo</span><span class="t-org">${esc(v.tipo)}</span></span>
      <span class="t-tit">${esc(v.titulo)}</span>
      <span class="marcas"><span>${esc(PAISES[v.pais] ?? "")}</span></span>
      <span class="t-res">${esc(v.resumen?.resumen ?? (v.minutos != null ? `Transcribiéndose, unos ${v.minutos} minutos cubiertos.` : "Recién empezada. El texto tarda unos 20 a 25 minutos en aparecer."))}</span>
      <span class="t-ver">Ver la transmisión</span></a>`;
  }

  function pintar(animar = true) {
    const f = s();
    App.recordar(NOM);
    const filas = filtradas();
    const extra = soloVivos();
    raiz.querySelector(".tr-cuenta").textContent = `${plural(filas.length, "sesión", "sesiones")} de ${miles(d.filas.length)}`
      + (vivos.length ? `, ${plural(vivos.length, "en vivo ahora", "en vivo ahora")}` : "");
    const lista = raiz.querySelector(".rejilla");
    lista.innerHTML = (f.vivo || !f.q ? extra.map(tarjetaVivo).join("") : "")
      + filas.slice(0, tope).map((t, i) => tarjeta(t, i)).join("")
      || `<div class="vacio">${f.vivo ? "No hay sesiones en vivo en este momento." : "Ninguna sesión con estos filtros."}</div>`;
    raiz.querySelector(".tr-mas").hidden = filas.length <= tope;
    raiz.querySelector(".tr-mas").textContent = `Ver ${miles(Math.min(filas.length - tope, TOPE))} más de ${miles(filas.length - tope)}`;
    lista.onclick = (e) => {
      const b = e.target.closest("[data-i]");
      if (!b) return;
      lista.querySelectorAll(".activa").forEach((x) => x.classList.remove("activa"));
      b.classList.add("activa");
      const t = filas[b.dataset.i];
      const camara = t.camara === "Sin confirmar" ? null : t.camara;
      conectarTranscripcion(App.detalle(fichaTranscripcion({ ...t, tipo: t.organo, camara, temas: temas(t) }, t.url)), t);
      App.alCerrar = () => b.classList.remove("activa");
    };
    if (animar) entrar(lista.children);
  }

  // Organo y camara dependen del pais elegido
  function filtros() {
    const f = s();
    const p = codigo(f.pais);
    const base = d.filas.filter((t) => !p || t.pais === p);
    raiz.querySelector(".tr-f").innerHTML = `
      <label class="check"><input type="checkbox" data-f="vivo"${f.vivo ? " checked" : ""}>Solo sesiones en vivo</label>
      ${campoFiltro({ k: "q", t: "Buscar en las sesiones", tipo: "texto" }, f)}
      ${p !== "EC" ? `<label class="campo">Cámara${campoFiltro({ k: "camara", t: "Cámara", todos: "Todas", ops: unicos(base.map((t) => t.camara).filter((c) => c && c !== "Sin confirmar")) }, f)}</label>` : ""}
      <label class="campo">Órgano${campoFiltro({ k: "organo", t: "Órgano", todos: "Todos", ops: unicos(base.map((t) => t.organo)) }, f)}</label>
      <label class="campo">Tema${campoFiltro({ k: "tema", t: "Tema", todos: "Todos", ops: unicos(base.flatMap(temas)) }, f)}</label>
      ${campoFiltro({ k: "ini", t: "Desde", tipo: "fecha" }, f)}${campoFiltro({ k: "fin", t: "Hasta", tipo: "fecha" }, f)}
      <button type="button" class="btn tr-limpiar">Limpiar filtros</button>`;
    raiz.querySelector(".tr-limpiar").onclick = () => {
      Object.assign(f, { q: "", organo: "", camara: "", tema: "", ini: "", fin: "", vivo: false });
      tope = TOPE; filtros(); pintar();
    };
  }

  async function mirarVivos() {
    try {
      vivos = (await App.pedir("seccion", { nombre: "vivos" })).datos ?? [];
      if (raiz?.isConnected && App.ruta === NOM) pintar(false);
    } catch { /* es un extra: sin aviso */ }
  }

  return {
    titulo: "Transcripciones", sub: "Sesiones del Congreso de Perú y de la Asamblea de Ecuador, con resumen", seccion: NOM,
    async abrir(cuerpo, ctrl) {
      raiz = cuerpo;
      tope = TOPE;
      cuerpo.innerHTML = espera();
      d = await App.seccion(NOM);
      if (App.ruta !== NOM) return;
      // La vista por semana y comision (la del reporte del viernes) vive en Agenda
      ctrl.innerHTML = `<button type="button" class="btn pri tr-semana">Vista por semana para el reporte</button>`;
      ctrl.querySelector(".tr-semana").onclick = () => {
        const p = App.pais === "EC" ? "ec" : "pe";
        const k = `agenda_${p}`;  // sin abrir Agenda aun, sus filtros por defecto los pone ella
        if (App.filtros[k]) App.filtros[k].tab = "trans";
        else sessionStorage.setItem(`vali:${k}`, JSON.stringify({ ...JSON.parse(sessionStorage.getItem(`vali:${k}`) || "{}"), tab: "trans" }));
        App.ir(`agenda_${p}`);
      };
      const f = s();
      // el pais se elige en el menu: lo que no exista en ese pais se suelta
      if (!d.filas.some((t) => t.organo === f.organo && (!App.pais || t.pais === App.pais))) f.organo = "";
      if (App.pais === "EC") f.camara = "";
      cuerpo.innerHTML = `<div class="tr-lay"><aside class="tr-f filtros"></aside>
        <section><p class="tr-cuenta nota"></p><div class="rejilla"></div><button type="button" class="mas tr-mas" hidden></button></section></div>`;
      filtros();
      // al escribir no se anima: cada tecla repintaria la entrada
      escucharFiltros(cuerpo.querySelector(".tr-f"), f, (k) => { tope = TOPE; pintar(k !== "q"); });
      cuerpo.querySelector(".tr-mas").onclick = () => { tope += TOPE; pintar(false); };
      pintar();
      mirarVivos();
      clearInterval(reloj);
      reloj = setInterval(() => { if (raiz.isConnected) mirarVivos(); else clearInterval(reloj); }, 90000);
    },
    nuevos(datos) { d = datos; if (raiz?.isConnected) pintar(); },
  };
})();
