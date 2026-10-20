// Simula google.script.run con datos de ejemplo, solo para la vista previa.
(function () {
  var M = [['Marta', 'marta'], ['Jorge', 'jorge'], ['Elena', 'elena'], ['Raúl', 'raul']].map(function (x) {
    return { nombre: x[0], email: x[1] + '@ejemplo.com' }; });
  function nom(id) { return M.filter(function (m) { return m.email.indexOf(id) === 0; })[0]; }
  function exp(n, tema, prop, resp, creo, venc, dias, estado, cat, conteo, extra) {
    return Object.assign({ numero: n, tema: tema, propuesta: prop, responsable: nom(resp).nombre,
      responsableEmail: nom(resp).email, soyResponsable: resp === 'marta', creadoPor: nom(creo).nombre,
      creadoPorEmail: nom(creo).email, vencimiento: venc, diasParaVencer: dias, estado: estado, categoria: cat,
      ronda: 1, notas: '', resultado: '', miVoto: '', finalizadoEl: '', quienesVotaron: [],
      conteo: conteo || { favor: 0, contra: 0, abstencion: 0, faltan: 4, necesarios: 3 } }, extra || {});
  }
  var datos = { acceso: true, nombreOng: 'Centro Comunitario (ejemplo)', yo: { email: 'marta@ejemplo.com', nombre: 'Marta' },
    miembros: M, mayoria: 3, proximaReunion: 'viernes 23/10 a las 19:30',
    expedientes: [
      exp(1, 'Compra de sillas para el salón', 'Comprar 20 sillas por $180.000', 'jorge', 'marta', '30/09/2026', -20, 'Finalizado', 'Finalizado', null,
        { resultado: '3 a favor, 1 en contra, 0 abstención', finalizadoEl: '28/09/2026' }),
      exp(2, 'Arreglo del techo', 'Aprobar el presupuesto de $250.000 de Techos Pérez', 'marta', 'elena', '22/10/2026', 2, 'Abierto', 'En curso',
        { favor: 2, contra: 0, abstencion: 0, faltan: 2, necesarios: 3 },
        { miVoto: 'A favor', notas: 'Hay otro presupuesto de $310.000.', quienesVotaron: ['Marta: A favor', 'Elena: A favor'] }),
      exp(3, 'Horario de verano', 'Pasar la reunión a las 20:00 desde diciembre', 'raul', 'raul', '13/11/2026', 24, 'Abierto', 'Pendiente', null,
        { ronda: 2, resultado: 'Ronda 1 sin mayoría (2 a favor, 2 en contra, 0 abstención). Se vuelve a votar el 23/10.' }),
      exp(4, 'Fiesta de fin de año', 'Organizar almuerzo el 13/12 con aporte de $5.000 por socio', 'elena', 'marta', '30/11/2026', 41, 'Aprobado', 'Terminado', null,
        { resultado: '4 a favor, 0 en contra, 0 abstención' }),
      exp(5, 'Pintura de la fachada', 'Pintar la fachada con voluntarios', 'marta', 'jorge', '15/10/2026', -5, 'Aprobado', 'Terminado', null,
        { resultado: '3 a favor, 0 en contra, 1 abstención' }),
      exp(6, 'Cambio de banco', 'Mudar la cuenta al Banco Nación', 'jorge', 'jorge', '10/10/2026', -10, 'Rechazado', 'Terminado', null,
        { resultado: '1 a favor, 3 en contra, 0 abstención' }),
      exp(7, 'Taller de computación', 'Dar un taller los martes con la notebook donada', 'elena', 'elena', '05/10/2026', -15, 'Finalizado', 'Finalizado', null,
        { resultado: '4 a favor, 0 en contra, 0 abstención', finalizadoEl: '02/10/2026' }),
      exp(8, 'Seguro del local', 'Renovar el seguro con la misma compañía', 'raul', 'marta', '04/11/2026', 15, 'Abierto', 'Pendiente', null)
    ] };
  function runner(h) {
    return new Proxy({}, { get: function (_, k) {
      if (k === 'withSuccessHandler') return function (f) { return runner(Object.assign({}, h, { ok: f })); };
      if (k === 'withFailureHandler') return function (f) { return runner(Object.assign({}, h, { err: f })); };
      return function () { setTimeout(function () { h.ok && h.ok(datos); }, 50); };
    } });
  }
  window.google = { script: { run: runner({}) } };
  window.confirm = function () { return true; };
})();
