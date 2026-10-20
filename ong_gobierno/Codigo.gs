/**
 * Sistema de expedientes y gobierno de la ONG — versión 1.
 *
 * Funciona sobre una planilla de Google (los datos) y se muestra como página
 * web dentro de Google Sites. Ver INSTALACION.md.
 *
 * Reglas de votación (acordadas):
 *   - Cada miembro tiene un voto: A favor, En contra o Abstención.
 *   - Un tema se cierra cuando una opción junta la mayoría del total de
 *     miembros (con 4 miembros: 3 votos), sin importar cuántos votaron.
 *   - Si votaron todos y ninguna opción llegó a la mayoría (por ejemplo 2 a 2),
 *     el tema queda abierto y se vuelve a votar en la reunión siguiente.
 *
 * Acceso: cada miembro entra con su enlace personal (o escribe su clave personal).
 * La aplicación corre con la cuenta de quien la instaló, así que los demás no
 * necesitan permisos de Google ni acceso a la planilla.
 *
 * Ciclo de un expediente (decidir y después hacer):
 *   Pendiente   abierto, nadie votó todavía en la ronda actual
 *   En curso    abierto, la votación está en marcha
 *   Terminado   ya se decidió: Aprobado o Rechazado
 *   Finalizado  estaba aprobado y el responsable marcó que ya lo hizo
 */

var HOJAS = {
  CONFIG: 'Configuracion',
  MIEMBROS: 'Miembros',
  EXPEDIENTES: 'Expedientes',
  VOTOS: 'Votos',
  HISTORIAL: 'Historial'
};

var COLUMNAS = {
  Configuracion: ['Clave', 'Valor', 'Explicación'],
  Miembros: ['Nombre', 'Email', 'Clave personal'],
  Expedientes: ['Número', 'Tema', 'Propuesta a votar', 'Responsable (email)', 'Vencimiento',
                'Estado', 'Ronda', 'Creado por', 'Creado el', 'Notas', 'Aviso enviado', 'Resultado',
                'Finalizado el'],
  Votos: ['Expediente', 'Ronda', 'Email', 'Voto', 'Fecha'],
  Historial: ['Fecha', 'Email', 'Acción', 'Detalle']
};

var CONFIG_INICIAL = [
  ['NOMBRE_ONG', 'Nuestra ONG', 'Nombre que aparece arriba en la página y en los mails'],
  ['DIA_REUNION', '5', 'Día de la reunión: 1=lunes ... 5=viernes ... 7=domingo'],
  ['HORA_REUNION', '19:30', 'Hora de la reunión (por ejemplo 19:30 o 20:00)'],
  ['DIAS_AVISO_VENCIMIENTO', '2', 'Cuántos días antes del vencimiento se avisa al responsable'],
  ['DIAS_AVISO_REUNION', '1', 'Cuántos días antes de la reunión se manda el recordatorio a todos'],
  ['URL_APP', '', 'Dirección de la página (la que termina en /exec). Se usa en los enlaces de los mails']
];

var LETRAS_CLAVE = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // sin 0/O ni 1/I, que se confunden

var VOTOS_VALIDOS = ['A favor', 'En contra', 'Abstención'];
var ESTADO_ABIERTO = 'Abierto';
var ESTADO_FINALIZADO = 'Finalizado';

// ---------------------------------------------------------------------------
// Lógica pura (sin Google): se prueba con node en pruebas/prueba_logica.js
// ---------------------------------------------------------------------------

/** Votos necesarios para cerrar un tema: más de la mitad del total de miembros. */
function mayoriaNecesaria(totalMiembros) {
  return Math.floor(totalMiembros / 2) + 1;
}

/**
 * Cuenta los votos de una ronda y dice cómo queda el tema.
 * @param {string[]} votos  un voto por miembro ('A favor' | 'En contra' | 'Abstención')
 * @param {number} totalMiembros
 * @return {{estado: string, favor: number, contra: number, abstencion: number,
 *           faltan: number, necesarios: number}}
 *   estado: 'Aprobado' | 'Rechazado' | 'Sin mayoría' | 'En votación'
 */
function resolverVotacion(votos, totalMiembros) {
  var necesarios = mayoriaNecesaria(totalMiembros);
  var r = { favor: 0, contra: 0, abstencion: 0, necesarios: necesarios };
  votos.forEach(function (v) {
    if (v === 'A favor') r.favor++;
    else if (v === 'En contra') r.contra++;
    else if (v === 'Abstención') r.abstencion++;
  });
  r.faltan = Math.max(0, totalMiembros - votos.length);
  if (r.favor >= necesarios) r.estado = 'Aprobado';
  else if (r.contra >= necesarios) r.estado = 'Rechazado';
  else if (r.faltan === 0) r.estado = 'Sin mayoría';
  else r.estado = 'En votación';
  return r;
}

/**
 * Categoría del tablero para un expediente.
 * @param {string} estado  valor de la columna Estado
 * @param {number} votosEnRonda  cuántos votaron en la ronda actual
 * @return {'Pendiente'|'En curso'|'Terminado'|'Finalizado'}
 */
function categoria(estado, votosEnRonda) {
  if (estado === ESTADO_FINALIZADO) return 'Finalizado';
  if (estado === 'Aprobado' || estado === 'Rechazado') return 'Terminado';
  return votosEnRonda > 0 ? 'En curso' : 'Pendiente';
}

/** Clave personal al azar de 8 letras y números fáciles de leer. */
function generarClave() {
  var c = '';
  for (var i = 0; i < 8; i++) c += LETRAS_CLAVE.charAt(Math.floor(Math.random() * LETRAS_CLAVE.length));
  return c;
}

/** Normaliza lo que escribe la persona: mayúsculas, sin espacios ni guiones. */
function normalizarClave(texto) {
  var c = String(texto || '').toUpperCase().replace(/[\s-]/g, '');
  return /^[A-Z0-9]{6,20}$/.test(c) ? c : '';
}

/** Fecha sin hora (medianoche del mismo día). */
function soloFecha(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Días de calendario desde `desde` hasta `hasta` (negativo si ya pasó). */
function diasEntre(desde, hasta) {
  var ms = soloFecha(hasta) - soloFecha(desde);
  return Math.round(ms / 86400000);
}

/**
 * Próxima reunión a partir de `desde` (incluye el mismo día si todavía no pasó la hora).
 * @param {number} diaReunion 1=lunes ... 7=domingo
 * @param {string} hora 'HH:MM'
 */
function proximaReunion(desde, diaReunion, hora) {
  var partes = String(hora).split(':');
  var h = Number(partes[0]), m = Number(partes[1] || 0);
  var objetivo = diaReunion % 7; // en JavaScript domingo = 0
  var d = new Date(desde.getFullYear(), desde.getMonth(), desde.getDate(), h, m);
  var suma = (objetivo - d.getDay() + 7) % 7;
  d.setDate(d.getDate() + suma);
  if (d <= desde) d.setDate(d.getDate() + 7);
  return d;
}

/** ¿Hay que avisarle hoy al responsable de este expediente? */
function debeAvisarVencimiento(exp, hoy, diasAviso) {
  // Se avisa mientras se vota y también si ya se aprobó pero todavía no se hizo.
  if (exp.estado !== ESTADO_ABIERTO && exp.estado !== 'Aprobado') return false;
  if (!(exp.vencimiento instanceof Date)) return false;
  if (exp.avisoEnviado) return false;
  var dias = diasEntre(hoy, exp.vencimiento);
  // Si el aviso se perdió un día (por ejemplo, el disparador no corrió), se manda igual
  // mientras no haya vencido.
  return dias >= 0 && dias <= diasAviso;
}

/** ¿Hoy toca mandar el recordatorio de la reunión? */
function esDiaDeAvisoReunion(hoy, diaReunion, diasAntes) {
  var objetivo = diaReunion % 7;
  return (hoy.getDay() + Number(diasAntes)) % 7 === objetivo;
}

// ---------------------------------------------------------------------------
// Instalación (la corre una sola vez la dueña de la planilla)
// ---------------------------------------------------------------------------

/** Crea las hojas, la configuración inicial y los avisos automáticos. */
function instalar() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  Object.keys(COLUMNAS).forEach(function (nombre) {
    var hoja = ss.getSheetByName(nombre) || ss.insertSheet(nombre);
    // Escribe los títulos (también agrega columnas nuevas a una planilla ya instalada).
    hoja.getRange(1, 1, 1, COLUMNAS[nombre].length).setValues([COLUMNAS[nombre]]).setFontWeight('bold');
    hoja.setFrozenRows(1);
  });

  var config = ss.getSheetByName(HOJAS.CONFIG);
  var clavesExistentes = config.getDataRange().getValues().map(function (f) { return f[0]; });
  CONFIG_INICIAL.forEach(function (fila) {
    if (clavesExistentes.indexOf(fila[0]) < 0) config.appendRow(fila);
  });

  var miembros = ss.getSheetByName(HOJAS.MIEMBROS);
  if (miembros.getLastRow() === 1) {
    miembros.appendRow(['(tu nombre)', Session.getEffectiveUser().getEmail(), '']);
  }
  completarClaves_();

  var hojaVacia = ss.getSheetByName('Hoja 1') || ss.getSheetByName('Sheet1');
  if (hojaVacia && hojaVacia.getLastRow() === 0 && ss.getSheets().length > 1) {
    ss.deleteSheet(hojaVacia);
  }

  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'revisionDiaria') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('revisionDiaria').timeBased().everyDays(1).atHour(8).create();

  var mensaje = 'Listo. Revisá la hoja "Miembros" (nombres, mails y claves) y la hoja ' +
    '"Configuracion". Cuando la página esté publicada, pegá su dirección en URL_APP y usá ' +
    'el menú ONG > Enviar enlaces personales.';
  try {
    SpreadsheetApp.getUi().alert(mensaje);
  } catch (e) {
    Logger.log(mensaje); // corrido desde el editor de Apps Script: no hay ventana para mostrar
  }
}

/** Menú en la planilla para quien la administra. */
function onOpen() {
  SpreadsheetApp.getUi().createMenu('ONG')
    .addItem('Instalar / reparar', 'instalar')
    .addItem('Enviar enlaces personales', 'enviarEnlaces')
    .addItem('Mandar avisos de hoy ahora', 'revisionDiaria')
    .addToUi();
}

// ---------------------------------------------------------------------------
// Página web
// ---------------------------------------------------------------------------

function doGet(e) {
  var plantilla = HtmlService.createTemplateFromFile('Index');
  plantilla.clave = normalizarClave(e && e.parameter ? e.parameter.c : '');
  return plantilla.evaluate()
    .setTitle('Expedientes')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/** Todo lo que la página necesita mostrar. */
function obtenerDatos(clave) {
  var yo = usuarioActual_(clave);
  var config = leerConfig_();
  if (!yo.miembro) {
    return { acceso: false, claveEscrita: !!normalizarClave(clave), nombreOng: config.NOMBRE_ONG };
  }
  var miembros = leerMiembros_().map(function (m) { return { nombre: m.nombre, email: m.email }; });
  var votos = leerVotos_();
  var tz = Session.getScriptTimeZone();
  var hoy = new Date();

  var expedientes = leerExpedientes_().map(function (e) {
    var deRonda = votos.filter(function (v) { return v.expediente === e.numero && v.ronda === e.ronda; });
    var conteo = resolverVotacion(deRonda.map(function (v) { return v.voto; }), miembros.length);
    var mio = deRonda.filter(function (v) { return v.email === yo.email; })[0];
    return {
      numero: e.numero,
      tema: e.tema,
      propuesta: e.propuesta,
      responsable: nombreDe_(miembros, e.responsable),
      responsableEmail: e.responsable,
      soyResponsable: e.responsable === yo.email,
      creadoPor: nombreDe_(miembros, e.creadoPor),
      creadoPorEmail: e.creadoPor,
      creadoEl: e.creadoEl ? Utilities.formatDate(e.creadoEl, tz, 'dd/MM/yyyy') : '',
      finalizadoEl: e.finalizadoEl ? Utilities.formatDate(e.finalizadoEl, tz, 'dd/MM/yyyy') : '',
      categoria: categoria(e.estado, deRonda.length),
      vencimiento: e.vencimiento ? Utilities.formatDate(e.vencimiento, tz, 'dd/MM/yyyy') : '',
      diasParaVencer: e.vencimiento ? diasEntre(hoy, e.vencimiento) : null,
      estado: e.estado,
      ronda: e.ronda,
      notas: e.notas,
      resultado: e.resultado,
      miVoto: mio ? mio.voto : '',
      conteo: conteo,
      quienesVotaron: deRonda.map(function (v) { return nombreDe_(miembros, v.email) + ': ' + v.voto; })
    };
  });

  var reunion = proximaReunion(hoy, Number(config.DIA_REUNION), config.HORA_REUNION);
  return {
    acceso: true,
    nombreOng: config.NOMBRE_ONG,
    yo: { email: yo.email, nombre: nombreDe_(miembros, yo.email) },
    miembros: miembros,
    mayoria: mayoriaNecesaria(miembros.length),
    proximaReunion: Utilities.formatDate(reunion, tz, "EEEE dd/MM 'a las' HH:mm"),
    expedientes: expedientes
  };
}

/** Alta de un expediente desde la página. */
function crearExpediente(clave, datos) {
  var yo = exigirMiembro_(clave);
  var tema = String(datos.tema || '').trim();
  var propuesta = String(datos.propuesta || '').trim();
  var responsable = String(datos.responsable || '').trim().toLowerCase();
  if (!tema) throw new Error('Falta el tema.');
  if (!propuesta) throw new Error('Falta la propuesta a votar.');
  if (!leerMiembros_().some(function (m) { return m.email === responsable; })) {
    throw new Error('El responsable tiene que ser uno de los miembros.');
  }
  var venc = parsearFecha_(datos.vencimiento);
  if (!venc) throw new Error('Falta la fecha de vencimiento.');
  if (diasEntre(new Date(), venc) < 0) throw new Error('La fecha de vencimiento ya pasó.');

  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var hoja = hoja_(HOJAS.EXPEDIENTES);
    var numero = leerExpedientes_().reduce(function (max, e) { return Math.max(max, e.numero); }, 0) + 1;
    hoja.appendRow([numero, tema, propuesta, responsable, venc, ESTADO_ABIERTO, 1,
                    yo.email, new Date(), String(datos.notas || '').trim(), '', '', '']);
    registrar_(yo.email, 'Nuevo expediente', '#' + numero + ' ' + tema);
  } finally {
    lock.releaseLock();
  }
  return obtenerDatos(clave);
}

/** Registra (o cambia) el voto del usuario en la ronda actual y cierra el tema si corresponde. */
function votar(clave, numero, voto) {
  var yo = exigirMiembro_(clave);
  if (VOTOS_VALIDOS.indexOf(voto) < 0) throw new Error('Voto no válido.');

  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var hojaExp = hoja_(HOJAS.EXPEDIENTES);
    var exps = leerExpedientes_();
    var exp = exps.filter(function (e) { return e.numero === Number(numero); })[0];
    if (!exp) throw new Error('No encuentro el expediente #' + numero + '.');
    if (exp.estado !== ESTADO_ABIERTO) throw new Error('Este tema ya está cerrado: ' + exp.estado + '.');

    var hojaVotos = hoja_(HOJAS.VOTOS);
    var filas = hojaVotos.getDataRange().getValues();
    var filaExistente = -1;
    for (var i = 1; i < filas.length; i++) {
      if (Number(filas[i][0]) === exp.numero && Number(filas[i][1]) === exp.ronda &&
          String(filas[i][2]).toLowerCase() === yo.email) {
        filaExistente = i + 1;
      }
    }
    if (filaExistente > 0) {
      hojaVotos.getRange(filaExistente, 4, 1, 2).setValues([[voto, new Date()]]);
    } else {
      hojaVotos.appendRow([exp.numero, exp.ronda, yo.email, voto, new Date()]);
    }
    registrar_(yo.email, 'Voto', '#' + exp.numero + ' ronda ' + exp.ronda + ': ' + voto);

    var miembros = leerMiembros_();
    var deRonda = leerVotos_().filter(function (v) {
      return v.expediente === exp.numero && v.ronda === exp.ronda;
    });
    var r = resolverVotacion(deRonda.map(function (v) { return v.voto; }), miembros.length);
    var resumen = r.favor + ' a favor, ' + r.contra + ' en contra, ' + r.abstencion + ' abstención';

    if (r.estado === 'Aprobado' || r.estado === 'Rechazado') {
      hojaExp.getRange(exp.fila, 6).setValue(r.estado);
      hojaExp.getRange(exp.fila, 12).setValue(resumen);
      registrar_('sistema', r.estado, '#' + exp.numero + ' (' + resumen + ')');
      avisarATodos_(miembros, 'Tema cerrado: ' + r.estado.toLowerCase() + ' — ' + exp.tema,
        '<p>El expediente <b>#' + exp.numero + ' — ' + escapar_(exp.tema) + '</b> quedó <b>' +
        r.estado.toUpperCase() + '</b>.</p><p>Votación: ' + resumen + '.</p>');
    } else if (r.estado === 'Sin mayoría') {
      var config = leerConfig_();
      var reunion = proximaReunion(new Date(), Number(config.DIA_REUNION), config.HORA_REUNION);
      var fechaReunion = Utilities.formatDate(reunion, Session.getScriptTimeZone(), 'dd/MM');
      hojaExp.getRange(exp.fila, 7).setValue(exp.ronda + 1);
      hojaExp.getRange(exp.fila, 12).setValue(
        'Ronda ' + exp.ronda + ' sin mayoría (' + resumen + '). Se vuelve a votar el ' + fechaReunion + '.');
      registrar_('sistema', 'Sin mayoría', '#' + exp.numero + ' ronda ' + exp.ronda + ' (' + resumen + ')');
      avisarATodos_(miembros, 'Sin mayoría: ' + exp.tema + ' se vota de nuevo',
        '<p>El expediente <b>#' + exp.numero + ' — ' + escapar_(exp.tema) +
        '</b> no alcanzó mayoría (' + resumen + ').</p><p>Se vuelve a votar en la reunión del ' +
        fechaReunion + '.</p>');
    }
  } finally {
    lock.releaseLock();
  }
  return obtenerDatos(clave);
}

/** El responsable de un expediente aprobado marca que ya lo hizo. */
function marcarHecho(clave, numero) {
  var yo = exigirMiembro_(clave);
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    var exp = leerExpedientes_().filter(function (e) { return e.numero === Number(numero); })[0];
    if (!exp) throw new Error('No encuentro el expediente #' + numero + '.');
    if (exp.estado !== 'Aprobado') throw new Error('Solo se puede marcar como hecho un tema aprobado.');
    if (exp.responsable !== yo.email) throw new Error('Solo el responsable puede marcarlo como hecho.');
    var hoja = hoja_(HOJAS.EXPEDIENTES);
    hoja.getRange(exp.fila, 6).setValue(ESTADO_FINALIZADO);
    hoja.getRange(exp.fila, 13).setValue(new Date());
    registrar_(yo.email, 'Finalizado', '#' + exp.numero + ' ' + exp.tema);
    var miembros = leerMiembros_();
    avisarATodos_(miembros, 'Hecho: ' + exp.tema,
      '<p>' + escapar_(nombreDe_(miembros, yo.email)) + ' marcó como <b>hecho</b> el expediente <b>#' +
      exp.numero + ' — ' + escapar_(exp.tema) + '</b>.</p>');
  } finally {
    lock.releaseLock();
  }
  return obtenerDatos(clave);
}

// ---------------------------------------------------------------------------
// Avisos automáticos (los corre el disparador diario de las 8)
// ---------------------------------------------------------------------------

function revisionDiaria() {
  var config = leerConfig_();
  var miembros = leerMiembros_();
  var hoy = new Date();
  var tz = Session.getScriptTimeZone();
  var hojaExp = hoja_(HOJAS.EXPEDIENTES);
  var diasAviso = Number(config.DIAS_AVISO_VENCIMIENTO);
  var expedientes = leerExpedientes_();

  expedientes.forEach(function (e) {
    if (!debeAvisarVencimiento(e, hoy, diasAviso)) return;
    var dias = diasEntre(hoy, e.vencimiento);
    var cuando = dias === 0 ? 'hoy' : dias === 1 ? 'mañana' : 'en ' + dias + ' días';
    MailApp.sendEmail({
      to: e.responsable,
      subject: 'Recordatorio: el expediente #' + e.numero + ' vence ' + cuando,
      htmlBody: '<p>Hola ' + escapar_(nombreDe_(miembros, e.responsable)) + ',</p>' +
        '<p>El expediente <b>#' + e.numero + ' — ' + escapar_(e.tema) + '</b>, del que sos responsable, ' +
        'vence <b>' + cuando + '</b> (' + Utilities.formatDate(e.vencimiento, tz, 'dd/MM/yyyy') + ').</p>' +
        enlace_(miembros.filter(function (m) { return m.email === e.responsable; })[0]) + pie_(config)
    });
    hojaExp.getRange(e.fila, 11).setValue(new Date());
    registrar_('sistema', 'Aviso de vencimiento', '#' + e.numero + ' a ' + e.responsable);
  });

  if (esDiaDeAvisoReunion(hoy, Number(config.DIA_REUNION), config.DIAS_AVISO_REUNION)) {
    var reunion = proximaReunion(hoy, Number(config.DIA_REUNION), config.HORA_REUNION);
    var abiertos = expedientes.filter(function (e) { return e.estado === ESTADO_ABIERTO; });
    var lista = abiertos.length
      ? '<ul>' + abiertos.map(function (e) {
          return '<li>#' + e.numero + ' — ' + escapar_(e.tema) + '</li>';
        }).join('') + '</ul>'
      : '<p>No hay temas abiertos.</p>';
    avisarATodos_(miembros,
      'Reunión ' + Utilities.formatDate(reunion, tz, "EEEE dd/MM 'a las' HH:mm"),
      '<p>Les recordamos la reunión del <b>' +
      Utilities.formatDate(reunion, tz, "EEEE dd/MM 'a las' HH:mm") + '</b>.</p>' +
      '<p>Temas abiertos para tratar y votar:</p>' + lista);
    registrar_('sistema', 'Recordatorio de reunión', abiertos.length + ' temas abiertos');
  }
}

// ---------------------------------------------------------------------------
// Ayudantes de la planilla
// ---------------------------------------------------------------------------

function hoja_(nombre) {
  var h = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(nombre);
  if (!h) throw new Error('Falta la hoja "' + nombre + '". Usá el menú ONG > Instalar.');
  return h;
}

function filas_(nombre) {
  return hoja_(nombre).getDataRange().getValues().slice(1);
}

function leerConfig_() {
  var c = {};
  CONFIG_INICIAL.forEach(function (fila) { c[fila[0]] = fila[1]; });
  filas_(HOJAS.CONFIG).forEach(function (f) {
    if (f[0] !== '' && f[1] !== '') {
      // Sheets convierte "19:30" en una hora: la volvemos a texto.
      c[f[0]] = f[1] instanceof Date
        ? Utilities.formatDate(f[1], Session.getScriptTimeZone(), 'HH:mm')
        : String(f[1]);
    }
  });
  return c;
}

function leerMiembros_() {
  return filas_(HOJAS.MIEMBROS)
    .filter(function (f) { return String(f[1]).indexOf('@') > 0; })
    .map(function (f, i) {
      return { fila: i + 2, nombre: String(f[0]).trim(), email: String(f[1]).trim().toLowerCase(),
               clave: normalizarClave(f[2]) };
    });
}

function leerExpedientes_() {
  return filas_(HOJAS.EXPEDIENTES).map(function (f, i) {
    return {
      fila: i + 2,
      numero: Number(f[0]),
      tema: String(f[1]),
      propuesta: String(f[2]),
      responsable: String(f[3]).trim().toLowerCase(),
      vencimiento: f[4] instanceof Date ? f[4] : null,
      estado: String(f[5]) || ESTADO_ABIERTO,
      ronda: Number(f[6]) || 1,
      creadoPor: String(f[7]).trim().toLowerCase(),
      creadoEl: f[8] instanceof Date ? f[8] : null,
      notas: String(f[9]),
      avisoEnviado: f[10] !== '',
      resultado: String(f[11]),
      finalizadoEl: f[12] instanceof Date ? f[12] : null
    };
  }).filter(function (e) { return e.numero > 0; });
}

function leerVotos_() {
  return filas_(HOJAS.VOTOS).map(function (f) {
    return { expediente: Number(f[0]), ronda: Number(f[1]), email: String(f[2]).toLowerCase(), voto: String(f[3]) };
  });
}

function registrar_(email, accion, detalle) {
  hoja_(HOJAS.HISTORIAL).appendRow([new Date(), email, accion, detalle]);
}

function usuarioActual_(clave) {
  var c = normalizarClave(clave);
  var m = c ? leerMiembros_().filter(function (x) { return x.clave === c; })[0] : null;
  return m ? { email: m.email, nombre: m.nombre, miembro: true } : { email: '', miembro: false };
}

function exigirMiembro_(clave) {
  var yo = usuarioActual_(clave);
  if (!yo.miembro) throw new Error('La clave personal no es válida. Volvé a entrar con el enlace del mail.');
  return yo;
}

/** Genera una clave personal a quien no tenga. */
function completarClaves_() {
  var hoja = hoja_(HOJAS.MIEMBROS);
  var usadas = {};
  leerMiembros_().forEach(function (m) { if (m.clave) usadas[m.clave] = true; });
  leerMiembros_().forEach(function (m) {
    if (m.clave) return;
    var c;
    do { c = generarClave(); } while (usadas[c]);
    usadas[c] = true;
    hoja.getRange(m.fila, 3).setValue(c);
  });
}

/** Menú: manda a cada miembro su enlace personal y su clave. */
function enviarEnlaces() {
  completarClaves_();
  var config = leerConfig_();
  var url = urlApp_();
  if (!url) {
    SpreadsheetApp.getUi().alert('Primero pegá la dirección de la página (la que termina en /exec) ' +
      'en la hoja Configuracion, fila URL_APP.');
    return;
  }
  var miembros = leerMiembros_();
  miembros.forEach(function (m) {
    MailApp.sendEmail({
      to: m.email,
      subject: 'Tu enlace personal al sistema de expedientes — ' + config.NOMBRE_ONG,
      htmlBody: '<p>Hola ' + escapar_(m.nombre) + ',</p>' +
        '<p>Este es <b>tu enlace personal</b> para ver los expedientes y votar. ' +
        'Guardalo como favorito y <b>no lo reenvíes</b>: quien lo tenga puede votar en tu nombre.</p>' +
        '<p style="font-size:20px"><a href="' + url + '?c=' + m.clave + '">Entrar al sistema de expedientes</a></p>' +
        '<p>Si te pide una clave, es: <b style="font-size:20px;letter-spacing:2px">' + m.clave + '</b></p>' +
        pie_(config)
    });
    registrar_('sistema', 'Enlace personal enviado', m.email);
  });
  SpreadsheetApp.getUi().alert('Listo: se mandó el enlace personal a ' + miembros.length + ' miembro(s).');
}

function urlApp_() {
  var config = leerConfig_();
  var url = String(config.URL_APP || '').trim();
  if (!url) {
    try { url = ScriptApp.getService().getUrl() || ''; } catch (e) { url = ''; }
  }
  return /\/exec$/.test(url) ? url : '';
}

function nombreDe_(miembros, email) {
  var m = miembros.filter(function (x) { return x.email === email; })[0];
  return m && m.nombre ? m.nombre : email;
}

function parsearFecha_(texto) {
  var p = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(texto || ''));
  return p ? new Date(Number(p[1]), Number(p[2]) - 1, Number(p[3])) : null;
}

/** Un mail por persona, para que cada uno reciba su propio enlace de acceso. */
function avisarATodos_(miembros, asunto, html) {
  var config = leerConfig_();
  miembros.forEach(function (m) {
    MailApp.sendEmail({ to: m.email, subject: asunto, htmlBody: html + enlace_(m) + pie_(config) });
  });
}

function enlace_(miembro) {
  var url = urlApp_();
  if (!url || !miembro || !miembro.clave) return '';
  return '<p><a href="' + url + '?c=' + miembro.clave + '">Abrir el sistema de expedientes</a></p>';
}

function pie_(config) {
  return '<p style="color:#666">— ' + escapar_(config.NOMBRE_ONG) + ' (mensaje automático)</p>';
}

function escapar_(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Permite probar la lógica pura con node (en Apps Script `module` no existe).
if (typeof module !== 'undefined') {
  module.exports = { mayoriaNecesaria: mayoriaNecesaria, resolverVotacion: resolverVotacion,
    diasEntre: diasEntre, proximaReunion: proximaReunion,
    debeAvisarVencimiento: debeAvisarVencimiento, categoria: categoria,
    generarClave: generarClave, normalizarClave: normalizarClave, esDiaDeAvisoReunion: esDiaDeAvisoReunion };
}
