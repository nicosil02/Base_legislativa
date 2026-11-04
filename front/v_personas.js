// Ficha de congresista o asambleista (consultas/personas.py): bancada, proyectos,
// votos en el Pleno, lo que dijo en las sesiones y las mesas que organizo.
VISTAS.personas = (() => {
  const f = () => App.f("personas", { id: "", q: "" });
  const CAMARA = { diputados: "Diputados", senado: "Senado", asamblea: "Asamblea Nacional" };
  const VOTO = { SI: "A favor", NO: "En contra", ABST: "Abstención" };
  let gente = null;

  const nombre = (p) => p.nombre.split(",").reverse().join(" ").trim().toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase());
  const etiqueta = (p) => `${nombre(p)} · ${CAMARA[p.camara]}${p.bancada ? `, ${p.bancada}` : ""}`;

  async function ficha(caja, p) {
    caja.innerHTML = espera(4);
    let r;
    try { r = await App.pedir("ficha_persona", { pais: p.pais, id: p.id }); } catch (e) { caja.innerHTML = `<div class="aviso">No se pudo armar la ficha: ${esc(e.message)}</div>`; return; }
    if (f().id !== p.id) return;
    const contra = r.votos.filter((v) => v.contra_bancada);
    caja.innerHTML = `<h2 class="sub-t">${esc(nombre(p))}</h2><div class="kpis"></div>
      <h2 class="grupo-t">Proyectos que firmó <span>${r.pls.length}${r.pls.some((x) => x.seguido) ? `, ${r.pls.filter((x) => x.seguido).length} que sigues` : ""}</span></h2>
      ${r.pls.slice(0, 40).map((x) => `<article class="fila pl"><div class="marcas"><span>${esc(x.pl)}</span><span>${esc(fechaCorta(x.fecha))}</span>
          ${x.primero ? "<span>Primer firmante</span>" : ""}${x.seguido ? `<span class="cli">${icono("estrella", 12)}Lo sigues</span>` : ""}</div>
          <h3>${esc(oracion(x.titulo ?? ""))}</h3><small>${esc(x.estado ?? "")}</small></article>`).join("")
        || `<div class="vacio">No firmó proyectos en este periodo, o la base todavía no los tiene.</div>`}
      ${p.pais === "PE" ? `<h2 class="grupo-t">Votos en el Pleno <span>${contra.length ? `${contra.length} contra la mayoría de su bancada, arriba` : "los últimos"}</span></h2>
      ${[...contra, ...r.votos.filter((v) => !v.contra_bancada)].slice(0, 25).map((v) => `<article class="fila"><div class="marcas"><span>${esc(fechaCorta(v.fecha))}</span>
          <span>${esc(VOTO[v.voto] ?? "No votó")}</span>${v.contra_bancada ? `<span class="cli">Contra su bancada</span>` : ""}</div><p>${esc(v.asunto)}</p></article>`).join("")
        || `<div class="vacio">Sin votaciones nominales registradas.</div>`}` : ""}
      <h2 class="grupo-t">Qué dijo en las sesiones <span>${r.sesiones.length}, las más recientes donde se le nombra (la transcripción automática puede escribir mal los apellidos)</span></h2>
      ${r.sesiones.map((x) => `<article class="fila"><div class="marcas"><span>${esc(fechaCorta(x.fecha))}</span><span>${esc(x.organo)}</span>
          <span>${x.menciones} ${x.menciones === 1 ? "mención" : "menciones"}</span>${enlaceIcono(x.url, "Ver la sesión")}</div>
          ${x.trozos.map((t) => `<p>«${esc(t)}»</p>`).join("")}</article>`).join("")
        || `<div class="vacio">No aparece en las sesiones transcritas.</div>`}
      ${r.mesas.length ? `<h2 class="grupo-t">Mesas técnicas que organizó <span>${r.mesas.length}</span></h2>
      ${r.mesas.map((m) => `<article class="fila"><div class="marcas"><span>${esc(fechaCorta(m.fecha))}</span>${enlaceIcono(m.url, "Abrir")}</div><h3>${esc(m.titulo ?? "")}</h3></article>`).join("")}` : ""}`;
    kpis(caja.querySelector(".kpis"), [
      [CAMARA[p.camara], "Cámara", PAISES[p.pais]],
      ...(p.pais === "PE" ? [
        [r.bancada ?? "—", "Bancada", "en su última votación"],
        [r.pct_alineado != null ? `${r.pct_alineado} %` : "—", "Vota con su bancada", `en ${r.votaciones} votaciones del Pleno`],
        [r.ausencias ?? "—", "No votó", "ausente, licencia o sin respuesta"]] : []),
      [r.pls.length, "Proyectos firmados", p.pais === "PE" ? "periodo 2026-2031" : "periodo 2025-2029"],
    ]);
    entrar(caja.querySelectorAll(".fila"));
  }

  return {
    titulo: "Congresistas y asambleístas", sub: "Qué firmó, cómo votó y qué dijo cada uno. Para el quién apoyó y quién cuestionó de las alertas.",
    async abrir(cuerpo) {
      cuerpo.innerHTML = `<div class="barra filtros"><label class="campo grande">Nombre o apellido
          <input type="search" class="p-q" list="p-lista" placeholder="Escribe un apellido" value="${esc(f().q)}"></label></div>
        <datalist id="p-lista"></datalist><div class="p-ficha"></div>`;
      const caja = cuerpo.querySelector(".p-ficha");
      if (!gente) {
        caja.innerHTML = espera(2);
        try { gente = await App.pedir("personas"); } catch (e) { caja.innerHTML = `<div class="aviso">No se pudo traer la lista: ${esc(e.message)}</div>`; return; }
        caja.innerHTML = "";
      }
      const lista = gente.filter((p) => !App.pais || p.pais === App.pais);
      cuerpo.querySelector("#p-lista").innerHTML = lista.map((p) => `<option value="${esc(etiqueta(p))}"></option>`).join("");
      const elegir = (texto) => {
        const p = lista.find((x) => etiqueta(x) === texto);
        if (!p) return;
        f().q = texto; f().id = p.id;
        ficha(caja, p);
      };
      const q = cuerpo.querySelector(".p-q");
      q.oninput = () => elegir(q.value);
      if (lista.some((x) => x.id === f().id)) elegir(f().q);  // al cambiar de pais puede quedar fuera
      else caja.innerHTML = `<div class="vacio">Escribe un apellido y elige de la lista. Hay ${lista.length} personas: los que votan en el Pleno peruano y los asambleístas que firmaron proyectos.</div>`;
    },
  };
})();
