// Espacio por cliente: lo marcado en la bandeja, lo ya enviado y los PL que sigue,
// y el Word del trafico con el formato del cliente (alerts/trafico.py).
VISTAS.clientes = (() => {
  const f = () => App.f("clientes", { cli: "", desde: "" });
  const hace = (dias) => new Date(Date.now() - dias * 864e5).toISOString().slice(0, 10);
  let d = null, elegidos = new Set();

  const fila = (k, x, marca, sel) => `<article class="fila noticia">
      <div class="marcas"><label class="check"><input type="checkbox" data-k="${esc(k)}"${sel ? " checked" : ""}>Va al Word</label>
        <span>${esc(marca)}</span><span>${esc(x.pais ?? "")}</span><span>${esc(fechaCorta(x.fecha))}</span>${enlaceIcono(x.url, "Abrir fuente")}</div>
      <h3>${esc(x.titulo)}</h3>${x.resumen ? `<p>${esc(x.resumen)}</p>` : ""}</article>`;

  function pintar(cuerpo) {
    const items = new Map([...d.marcadas.map((m) => [`m:${m.clave}`, m]), ...d.enviadas.map((e, i) => [`e:${i}`, e])]);
    cuerpo.querySelector(".c-datos").innerHTML = `
      <h2 class="grupo-t">Marcado en la bandeja <span>${d.marcadas.length}, Interesante o Alertar en el Panel</span></h2>
      ${d.marcadas.map((m) => fila(`m:${m.clave}`, m, m.estado === "alertar" ? "Alertada" : "Interesante", elegidos.has(`m:${m.clave}`))).join("")
        || `<div class="vacio">Nada marcado para este cliente desde esa fecha. Lo que marques como Interesante en el Panel aparece aquí.</div>`}
      <h2 class="grupo-t">Ya enviado <span>${d.enviadas.length}, del historial de alertas, para no repetir</span></h2>
      ${d.enviadas.map((e, i) => fila(`e:${i}`, e, "Enviada", elegidos.has(`e:${i}`))).join("") || `<div class="vacio">Sin alertas guardadas en el historial desde esa fecha.</div>`}
      <h2 class="grupo-t">Lo que viene en agenda <span>${d.agenda.length}, sesiones de los próximos días con un tema o un proyecto suyo</span></h2>
      ${d.agenda.map((a) => `<article class="fila"><div class="marcas"><span>${esc(PAISES[a.pais] ?? a.pais)}</span><span>${esc(a.cuando)}</span></div>
        <h3>${esc(a.nombre)}</h3>${a.puntos.map((p) => `<p>${esc(p)}</p>`).join("")}${a.pls.length ? `<small>Ve ${esc(a.pls.join(", "))}, que sigues</small>` : ""}</article>`).join("")
        || `<div class="vacio">Ninguna sesión próxima toca sus temas ni sus proyectos.</div>`}
      <details class="datos-pl"><summary>Proyectos que sigue (${d.seguidos.length})</summary>
        ${d.seguidos.map((p) => `<p><b>${esc(p.pais)} ${esc(p.pl)}</b> ${esc(p.estado ?? "")}. ${esc(p.titulo.slice(0, 160))}</p>`).join("")}</details>`;
    cuerpo.querySelector(".c-datos").onchange = (e) => {
      const k = e.target.dataset?.k;
      if (!k) return;
      if (e.target.checked) elegidos.add(k); else elegidos.delete(k);
      contar(cuerpo);
    };
    cuerpo.items = items;
    contar(cuerpo);
  }

  function contar(cuerpo) {
    const b = cuerpo.querySelector(".c-word");
    b.disabled = !elegidos.size;
    b.textContent = elegidos.size ? `Armar el Word con ${elegidos.size} ${elegidos.size === 1 ? "tema" : "temas"}` : "Elige qué va al Word";
    const t = cuerpo.querySelector(".c-ttw");
    t.hidden = !d?.ttw;
    t.disabled = !elegidos.size;
  }

  async function cargar(cuerpo) {
    const caja = cuerpo.querySelector(".c-datos");
    caja.innerHTML = espera(3);
    try {
      d = await App.pedir("cliente_espacio", { cliente: f().cli, desde: f().desde });
      elegidos = new Set(d.marcadas.map((m) => `m:${m.clave}`));
      pintar(cuerpo);
    } catch (e) { caja.innerHTML = `<div class="aviso">No se pudo traer el espacio del cliente: ${esc(e.message)}</div>`; }
  }

  return {
    titulo: "Espacio por cliente", sub: "Lo que marcaste, lo ya enviado y los proyectos que sigue. Arma el Word del tráfico.",
    async abrir(cuerpo, ctrl) {
      const lista = Object.keys(App.d.clientes);
      f().cli ||= lista[0];
      // Bayer manda el trafico cada dos semanas; el resto, semanal
      f().desde ||= hace(f().cli === "bayer" ? 14 : 7);
      ctrl.innerHTML = `<div class="r-cli"></div>`;
      cuerpo.innerHTML = `<p class="nota c-ayuda">Para armar el tráfico del cliente. Junta lo que marcaste como <b>Interesante</b> o <b>Alertar</b> en el Panel
          y las alertas que guardaste en su historial desde Redactar alerta. Si no marcas nada durante la semana, esta página sale vacía.</p>
        <div class="barra filtros"><label class="campo">Desde<input type="date" class="c-desde" value="${esc(f().desde)}"></label>
          <button type="button" class="btn pri c-word" disabled>Elige qué va al Word</button>
          <button type="button" class="btn c-ttw" hidden>Topics to Watch en inglés</button><span class="nota c-estado"></span></div>
        <div class="c-datos"></div>`;
      botonesCliente(ctrl.querySelector(".r-cli"), lista, f().cli, (v) => {
        f().cli = v; f().desde = hace(v === "bayer" ? 14 : 7);
        cuerpo.querySelector(".c-desde").value = f().desde;
        cargar(cuerpo);
      }, false);
      cuerpo.querySelector(".c-desde").onchange = (e) => { f().desde = e.target.value; cargar(cuerpo); };
      const armar = (formato) => async (e) => {
        const b = e.currentTarget, estado = cuerpo.querySelector(".c-estado");
        const items = [...elegidos].map((k) => cuerpo.items.get(k)).filter(Boolean)
          .map(({ titulo, url, pais, resumen }) => ({ titulo, url, pais, resumen }));
        b.disabled = true;
        estado.textContent = "Leyendo cada fuente y redactando, 20 a 60 segundos…";
        try {
          const b64 = await App.pedir("cliente_word", { cliente: f().cli, items, formato });
          const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
          const a = document.createElement("a");
          a.href = URL.createObjectURL(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
          a.download = `${formato === "ttw" ? "Topics to Watch" : "Tráfico"} ${App.nombre(f().cli)} ${new Date().toLocaleDateString("es-PE").replaceAll("/", "-")}.docx`;
          a.click();
          estado.textContent = "Listo. Revisa el Word antes de mandarlo.";
        } catch (err) { estado.textContent = `No se pudo armar el Word: ${err.message}`; }
        contar(cuerpo);
      };
      cuerpo.querySelector(".c-word").onclick = armar("trafico");
      cuerpo.querySelector(".c-ttw").onclick = armar("ttw");
      cargar(cuerpo);
    },
  };
})();
