// Pruebas de las reglas de votación y avisos. Correr con: node ong_gobierno/pruebas/prueba_logica.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Module = require('module');

const archivo = path.join(__dirname, '..', 'Codigo.gs');
const m = new Module(archivo);
m._compile(fs.readFileSync(archivo, 'utf8'), archivo);
const L = m.exports;

let ok = 0;
function prueba(nombre, fn) { fn(); ok++; console.log('ok -', nombre); }

prueba('con 4 miembros la mayoría es 3', () => {
  assert.strictEqual(L.mayoriaNecesaria(4), 3);
  assert.strictEqual(L.mayoriaNecesaria(5), 3);
});

prueba('3 a favor aprueba aunque falte uno', () => {
  const r = L.resolverVotacion(['A favor', 'A favor', 'A favor'], 4);
  assert.strictEqual(r.estado, 'Aprobado');
});

prueba('3 en contra rechaza', () => {
  assert.strictEqual(L.resolverVotacion(['En contra', 'En contra', 'A favor', 'En contra'], 4).estado, 'Rechazado');
});

prueba('2 a 2 queda sin mayoría (se vota el viernes siguiente)', () => {
  assert.strictEqual(L.resolverVotacion(['A favor', 'A favor', 'En contra', 'En contra'], 4).estado, 'Sin mayoría');
});

prueba('2 a favor y 1 en contra con uno sin votar: sigue en votación (no alcanza con 2)', () => {
  const r = L.resolverVotacion(['A favor', 'A favor', 'En contra'], 4);
  assert.strictEqual(r.estado, 'En votación');
  assert.strictEqual(r.faltan, 1);
});

prueba('2 a favor y 2 abstenciones: sin mayoría', () => {
  assert.strictEqual(L.resolverVotacion(['A favor', 'Abstención', 'A favor', 'Abstención'], 4).estado, 'Sin mayoría');
});

prueba('próxima reunión: un martes apunta al viernes de esa semana a las 19:30', () => {
  const martes = new Date(2026, 9, 20, 10, 0); // martes 20/10/2026
  const r = L.proximaReunion(martes, 5, '19:30');
  assert.deepStrictEqual([r.getDate(), r.getDay(), r.getHours(), r.getMinutes()], [23, 5, 19, 30]);
});

prueba('próxima reunión: un viernes después de la hora pasa al viernes siguiente', () => {
  const viernesNoche = new Date(2026, 9, 23, 21, 0);
  assert.strictEqual(L.proximaReunion(viernesNoche, 5, '19:30').getDate(), 30);
  const viernesTarde = new Date(2026, 9, 23, 15, 0);
  assert.strictEqual(L.proximaReunion(viernesTarde, 5, '20:00').getDate(), 23);
});

prueba('aviso de vencimiento: dos días antes sí, tres días antes no', () => {
  const hoy = new Date(2026, 9, 20, 8, 0);
  const exp = (dia, extra) => Object.assign({ estado: 'Abierto', vencimiento: new Date(2026, 9, dia), avisoEnviado: false }, extra);
  assert.strictEqual(L.debeAvisarVencimiento(exp(22), hoy, 2), true);
  assert.strictEqual(L.debeAvisarVencimiento(exp(23), hoy, 2), false);
  assert.strictEqual(L.debeAvisarVencimiento(exp(21), hoy, 2), true);   // si se salteó un día, igual avisa
  assert.strictEqual(L.debeAvisarVencimiento(exp(19), hoy, 2), false);  // ya vencido
  assert.strictEqual(L.debeAvisarVencimiento(exp(22, { avisoEnviado: true }), hoy, 2), false);
  assert.strictEqual(L.debeAvisarVencimiento(exp(22, { estado: 'Aprobado' }), hoy, 2), true);  // aprobado pero no hecho
  assert.strictEqual(L.debeAvisarVencimiento(exp(22, { estado: 'Rechazado' }), hoy, 2), false);
  assert.strictEqual(L.debeAvisarVencimiento(exp(22, { estado: 'Finalizado' }), hoy, 2), false);
});

prueba('recordatorio de reunión: el jueves si la reunión es el viernes y se avisa 1 día antes', () => {
  assert.strictEqual(L.esDiaDeAvisoReunion(new Date(2026, 9, 22), 5, 1), true);  // jueves
  assert.strictEqual(L.esDiaDeAvisoReunion(new Date(2026, 9, 21), 5, 1), false); // miércoles
  assert.strictEqual(L.esDiaDeAvisoReunion(new Date(2026, 9, 25), 1, 1), true);  // domingo, reunión lunes
});

prueba('categorías del tablero: pendiente, en curso, terminado, finalizado', () => {
  assert.strictEqual(L.categoria('Abierto', 0), 'Pendiente');
  assert.strictEqual(L.categoria('Abierto', 2), 'En curso');
  assert.strictEqual(L.categoria('Aprobado', 3), 'Terminado');
  assert.strictEqual(L.categoria('Rechazado', 4), 'Terminado');
  assert.strictEqual(L.categoria('Finalizado', 3), 'Finalizado');
});

prueba('claves personales: 8 caracteres legibles, distintas, y se aceptan con espacios o minúsculas', () => {
  const vistas = new Set();
  for (let i = 0; i < 200; i++) {
    const c = L.generarClave();
    assert.match(c, /^[A-HJ-NP-Z2-9]{8}$/);
    vistas.add(c);
  }
  assert.ok(vistas.size > 195);
  assert.strictEqual(L.normalizarClave(' abcd-2345 '), 'ABCD2345');
  assert.strictEqual(L.normalizarClave('<script>'), '');
  assert.strictEqual(L.normalizarClave(''), '');
  assert.strictEqual(L.normalizarClave(undefined), '');
});

console.log(`\n${ok} pruebas pasaron.`);
