// Simula google.script.run con datos de ejemplo, solo para la vista previa.
(function () {
  var miembros = [
    { nombre: 'Marta', email: 'marta@ejemplo.com' }, { nombre: 'Jorge', email: 'jorge@ejemplo.com' },
    { nombre: 'Elena', email: 'elena@ejemplo.com' }, { nombre: 'Raúl', email: 'raul@ejemplo.com' }];
  var datos = { acceso: true, nombreOng: 'Centro Comunitario (ejemplo)', yo: { email: 'marta@ejemplo.com', nombre: 'Marta' },
    miembros: miembros, mayoria: 3, proximaReunion: 'viernes 23/10 a las 19:30',
    expedientes: [
      { numero: 1, tema: 'Compra de sillas para el salón', propuesta: 'Comprar 20 sillas por $180.000', responsable: 'Jorge',
        vencimiento: '30/09/2026', diasParaVencer: -20, estado: 'Aprobado', ronda: 1, notas: '', resultado: '3 a favor, 1 en contra, 0 abstención',
        miVoto: '', conteo: {}, quienesVotaron: [] },
      { numero: 2, tema: 'Arreglo del techo', propuesta: 'Aprobar el presupuesto de $250.000 de Techos Pérez', responsable: 'Marta',
        soyResponsable: true, vencimiento: '22/10/2026', diasParaVencer: 2, estado: 'Abierto', ronda: 1, notas: 'Hay otro presupuesto de $310.000.',
        resultado: '', miVoto: 'A favor', conteo: { favor: 2, contra: 0, abstencion: 0, faltan: 2, necesarios: 3 },
        quienesVotaron: ['Marta: A favor', 'Elena: A favor'] },
      { numero: 3, tema: 'Horario de verano', propuesta: 'Pasar la reunión a las 20:00 desde diciembre', responsable: 'Raúl',
        vencimiento: '13/11/2026', diasParaVencer: 24, estado: 'Abierto', ronda: 2, notas: '',
        resultado: 'Ronda 1 sin mayoría (2 a favor, 2 en contra, 0 abstención). Se vuelve a votar el 23/10.',
        miVoto: '', conteo: { favor: 0, contra: 0, abstencion: 0, faltan: 4, necesarios: 3 }, quienesVotaron: [] }
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
