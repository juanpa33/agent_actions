"""Simulación de una cuenta real: acciones, caja, dividendos y libro de operaciones.

A diferencia del backtest, que trabaja con porcentajes, acá se cuentan acciones
enteras y pesos. Sirve para responder "¿cuánta plata hubiera hecho?" y, sobre
todo, para ver el detalle de cada operación en lugar de un número final que no
se puede auditar.

Dos reglas que este módulo respeta con rigor:

1. NO SE PUEDE VER EL FUTURO. Las decisiones de cada día usan solo precios hasta
   ese día. La única excepción está en `simular_oraculo`, que existe
   explícitamente para medir cuánto se pierde por no ser adivino, y está
   marcada como imposible de ejecutar en la realidad.

2. LOS DIVIDENDOS NO SE CUENTAN DOS VECES. Requiere precios SIN ajustar por
   dividendos (ver `yahoo.fetch_prices_and_dividends`). Si se usaran precios
   ajustados, el dividendo ya estaría dentro del precio y sumarlo de nuevo
   inflaría la ganancia.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .backtest import CostModel


@dataclass
class Transaccion:
    fecha: pd.Timestamp
    tipo: str               # COMPRA, VENTA, DIVIDENDO
    acciones: float
    precio: float
    bruto: float
    costos: float
    neto: float             # efecto sobre la caja (negativo si compra)
    acciones_despues: float
    caja_despues: float
    nota: str = ""


@dataclass
class ConfigEscalonada:
    """Estrategia de posiciones parciales: vender de a pedazos, recomprar en bajas."""

    acciones_objetivo: int = 100
    """Cantidad de acciones de la posición completa."""

    comprar_hasta_pct_del_minimo: float = 0.10
    """Comprar cuando el precio está a un 10% o menos por encima del mínimo."""

    vender_desde_pct_del_maximo: float = 0.95
    """Vender cuando el precio alcanza el 95% o más de su máximo."""

    fraccion_venta: float = 0.25
    """Qué porción de la tenencia actual se vende en cada toma de ganancia."""

    fraccion_nucleo: float = 0.25
    """Porción de la posición inicial que NUNCA se vende.

    La idea detrás: si el activo sube para siempre, vender todo deja al inversor
    afuera de manera permanente. Guardar un núcleo es la protección contra el
    escenario en que la regla de venta se equivoca sistemáticamente."""

    dias_minimos_entre_operaciones: int = 21
    """Evita vender cinco veces en la misma semana. Cada operación paga costos."""

    reinvertir_dividendos: bool = False
    """False = los dividendos quedan en caja y se pueden retirar.
    True = se usan para comprar más acciones cuando haya señal de compra."""

    ventana: str | int = "expanding"
    """'expanding' = mínimos y máximos históricos. Un entero = ventana móvil."""

    min_history: int = 252


@dataclass
class ResultadoSimulacion:
    nombre: str
    transacciones: list[Transaccion]
    capital_inicial: float
    valor_final: float
    acciones_finales: float
    caja_final: float
    dividendos_cobrados: float
    costos_totales: float
    precio_inicial: float
    precio_final: float
    fecha_inicio: pd.Timestamp | None = None
    serie_patrimonio: pd.Series = field(default_factory=pd.Series)

    @property
    def nunca_opero(self) -> bool:
        return not any(t.tipo in ("COMPRA", "VENTA") for t in self.transacciones)

    @property
    def ganancia(self) -> float:
        return self.valor_final - self.capital_inicial

    @property
    def retorno_pct(self) -> float:
        return self.ganancia / self.capital_inicial if self.capital_inicial else float("nan")

    @property
    def n_compras(self) -> int:
        return sum(1 for t in self.transacciones if t.tipo == "COMPRA")

    @property
    def n_ventas(self) -> int:
        return sum(1 for t in self.transacciones if t.tipo == "VENTA")

    def resumen(self, moneda: str = "USD") -> str:
        if self.nunca_opero:
            return (
                f"{self.nombre}\n"
                f"  NUNCA ABRIÓ POSICIÓN. La regla de compra no se cumplió ni una vez "
                f"en todo el período.\n"
                f"  El capital quedó en efectivo: {moneda} {self.capital_inicial:,.2f}. "
                f"Ganancia: {moneda} 0,00 (0,0%)"
            )
        lineas = [
            f"{self.nombre}",
            f"  Capital inicial:        {moneda} {self.capital_inicial:>12,.2f}",
            f"  Valor final:            {moneda} {self.valor_final:>12,.2f}",
            f"    - acciones ({self.acciones_finales:g} x {self.precio_final:,.2f}): "
            f"{moneda} {self.acciones_finales * self.precio_final:>12,.2f}",
            f"    - caja:               {moneda} {self.caja_final:>12,.2f}",
            f"  GANANCIA:               {moneda} {self.ganancia:>12,.2f}  "
            f"({self.retorno_pct * 100:+.1f}%)",
            f"  Dividendos cobrados:    {moneda} {self.dividendos_cobrados:>12,.2f}",
            f"  Costos pagados:         {moneda} {self.costos_totales:>12,.2f}",
            f"  Operaciones:            {self.n_compras} compras, {self.n_ventas} ventas",
        ]
        return "\n".join(lineas)

    def libro(self, maximo: int = 40) -> str:
        """Libro de operaciones, para poder auditar cada movimiento."""
        if not self.transacciones:
            return "  (no hubo operaciones)"

        lineas = [
            f"  {'Fecha':<12} {'Tipo':<10} {'Acc.':>8} {'Precio':>10} "
            f"{'Neto':>13} {'Tenencia':>9} {'Caja':>13}"
        ]
        mostrar = self.transacciones[:maximo]
        for t in mostrar:
            lineas.append(
                f"  {t.fecha:%Y-%m-%d} {t.tipo:<10} {t.acciones:>8.2f} "
                f"{t.precio:>10,.2f} {t.neto:>13,.2f} "
                f"{t.acciones_despues:>9.2f} {t.caja_despues:>13,.2f}"
            )
        if len(self.transacciones) > maximo:
            lineas.append(f"  ... y {len(self.transacciones) - maximo} operaciones más")
        return "\n".join(lineas)


def _extremos(precios: pd.Series, config: ConfigEscalonada):
    if config.ventana == "expanding":
        return (
            precios.expanding(min_periods=config.min_history).min(),
            precios.expanding(min_periods=config.min_history).max(),
        )
    w = int(config.ventana)
    return (
        precios.rolling(w, min_periods=w).min(),
        precios.rolling(w, min_periods=w).max(),
    )


def fecha_primera_senal(precios: pd.Series, config: ConfigEscalonada | None = None) -> pd.Timestamp:
    """Primera fecha en que las señales están definidas.

    Todas las estrategias que se comparen deben arrancar acá. Si una empieza
    antes, opera sobre un período que las otras no tuvieron, y la comparación
    mide la diferencia de fechas en lugar de la diferencia de estrategias.
    """
    cfg = config or ConfigEscalonada()
    px = precios.dropna()
    minimo, _ = _extremos(px, cfg)
    validas = minimo.dropna().index
    if len(validas) == 0:
        raise ValueError(
            f"La serie tiene {len(px)} ruedas: insuficientes para calcular "
            f"mínimos con {cfg.min_history} de historia mínima."
        )
    return validas[0]


def simular_escalonada(
    precios: pd.Series,
    dividendos: pd.Series | None = None,
    config: ConfigEscalonada | None = None,
    costos: CostModel | None = None,
    nombre: str = "Escalonada (vender de a pedazos)",
) -> ResultadoSimulacion:
    """Simula comprar cerca de mínimos y vender PARCIALMENTE cerca de máximos.

    Mecánica, día a día y usando solo información pasada:
      - Si es fecha de dividendo y hay acciones -> entra plata a la caja.
      - Si el precio está cerca del máximo y la tenencia supera al núcleo
        -> vende `fraccion_venta` de lo que tiene.
      - Si el precio está cerca del mínimo y hay caja -> recompra hasta el objetivo.
      - Entre medio, no hace nada.

    La ejecución es al precio del día siguiente al de la señal, igual que en el
    backtest: al cierre del día de la señal ese precio todavía no era operable.
    """
    cfg = config or ConfigEscalonada()
    costo = costos or CostModel.us_equity()
    px = precios.dropna()
    div = dividendos if dividendos is not None else pd.Series(dtype="float64")

    minimo, maximo = _extremos(px, cfg)

    # El capital inicial es el necesario para comprar la posición objetivo al
    # primer precio con señal definida.
    primer_valido = minimo.dropna().index
    if len(primer_valido) == 0:
        raise ValueError(
            f"La serie tiene {len(px)} ruedas: insuficientes para calcular "
            f"mínimos con {cfg.min_history} de historia mínima."
        )
    inicio = primer_valido[0]
    capital_inicial = cfg.acciones_objetivo * float(px.loc[inicio])

    caja = capital_inicial
    acciones = 0.0
    dividendos_cobrados = 0.0
    costos_totales = 0.0
    transacciones: list[Transaccion] = []
    ultima_operacion: pd.Timestamp | None = None
    patrimonio = pd.Series(np.nan, index=px.index, dtype="float64")

    fechas = list(px.index)
    for i, ts in enumerate(fechas):
        precio_hoy = float(px.loc[ts])

        # --- Dividendos: se cobran por las acciones en cartera a esa fecha ---
        if ts in div.index and acciones > 0:
            por_accion = float(div.loc[ts])
            bruto = por_accion * acciones
            caja += bruto
            dividendos_cobrados += bruto
            transacciones.append(
                Transaccion(ts, "DIVIDENDO", acciones, por_accion, bruto, 0.0, bruto,
                            acciones, caja, f"{por_accion:.4f} por acción")
            )

        patrimonio.loc[ts] = acciones * precio_hoy + caja

        m_bajo, m_alto = minimo.get(ts, np.nan), maximo.get(ts, np.nan)
        if np.isnan(m_bajo) or np.isnan(m_alto) or i + 1 >= len(fechas):
            continue

        if ultima_operacion is not None:
            if (ts - ultima_operacion).days < cfg.dias_minimos_entre_operaciones:
                continue

        # La señal se evalúa hoy; la ejecución es mañana, al precio de mañana.
        fecha_ejecucion = fechas[i + 1]
        precio_ejecucion = float(px.loc[fecha_ejecucion])

        cerca_del_maximo = precio_hoy / m_alto >= cfg.vender_desde_pct_del_maximo
        cerca_del_minimo = (precio_hoy / m_bajo - 1.0) <= cfg.comprar_hasta_pct_del_minimo
        nucleo = cfg.acciones_objetivo * cfg.fraccion_nucleo

        if cerca_del_maximo and acciones > nucleo:
            a_vender = min(acciones * cfg.fraccion_venta, acciones - nucleo)
            if a_vender > 0.01:
                bruto = a_vender * precio_ejecucion
                comision = bruto * costo.total_one_way
                caja += bruto - comision
                acciones -= a_vender
                costos_totales += comision
                ultima_operacion = fecha_ejecucion
                transacciones.append(
                    Transaccion(fecha_ejecucion, "VENTA", a_vender, precio_ejecucion,
                                bruto, comision, bruto - comision, acciones, caja,
                                f"a {precio_hoy / m_alto:.0%} del máximo")
                )

        elif cerca_del_minimo and acciones < cfg.acciones_objetivo:
            faltan = cfg.acciones_objetivo - acciones
            asequibles = caja / (precio_ejecucion * (1.0 + costo.total_one_way))
            a_comprar = min(faltan, asequibles)
            if a_comprar > 0.01:
                bruto = a_comprar * precio_ejecucion
                comision = bruto * costo.total_one_way
                caja -= bruto + comision
                acciones += a_comprar
                costos_totales += comision
                ultima_operacion = fecha_ejecucion
                transacciones.append(
                    Transaccion(fecha_ejecucion, "COMPRA", a_comprar, precio_ejecucion,
                                bruto, comision, -(bruto + comision), acciones, caja,
                                f"a {(precio_hoy / m_bajo - 1) * 100:.0f}% del mínimo")
                )

    precio_final = float(px.iloc[-1])
    return ResultadoSimulacion(
        nombre=nombre,
        transacciones=transacciones,
        capital_inicial=capital_inicial,
        valor_final=acciones * precio_final + caja,
        acciones_finales=acciones,
        caja_final=caja,
        dividendos_cobrados=dividendos_cobrados,
        costos_totales=costos_totales,
        precio_inicial=float(px.loc[inicio]),
        precio_final=precio_final,
        fecha_inicio=inicio,
        serie_patrimonio=patrimonio.dropna(),
    )


def simular_comprar_y_mantener(
    precios: pd.Series,
    dividendos: pd.Series | None = None,
    acciones: int = 100,
    costos: CostModel | None = None,
    desde: pd.Timestamp | None = None,
) -> ResultadoSimulacion:
    """Comprar las acciones una vez y no tocar nada, cobrando los dividendos."""
    costo = costos or CostModel.us_equity()
    px = precios.dropna()
    div = dividendos if dividendos is not None else pd.Series(dtype="float64")

    inicio = desde if desde is not None else px.index[0]
    precio_compra = float(px.loc[inicio])
    capital = acciones * precio_compra
    comision = capital * costo.total_one_way
    caja = -comision
    dividendos_cobrados = 0.0

    transacciones = [
        Transaccion(inicio, "COMPRA", acciones, precio_compra, capital, comision,
                    -(capital + comision), acciones, caja, "compra inicial")
    ]

    for ts, por_accion in div.items():
        if ts >= inicio and ts <= px.index[-1]:
            bruto = float(por_accion) * acciones
            caja += bruto
            dividendos_cobrados += bruto
            transacciones.append(
                Transaccion(ts, "DIVIDENDO", acciones, float(por_accion), bruto, 0.0,
                            bruto, acciones, caja, "")
            )

    precio_final = float(px.iloc[-1])
    ventana = px.loc[inicio:]
    return ResultadoSimulacion(
        nombre="Comprar y mantener",
        transacciones=transacciones,
        capital_inicial=capital,
        valor_final=acciones * precio_final + caja,
        acciones_finales=float(acciones),
        caja_final=caja,
        dividendos_cobrados=dividendos_cobrados,
        costos_totales=comision,
        precio_inicial=precio_compra,
        precio_final=precio_final,
        fecha_inicio=inicio,
        serie_patrimonio=(ventana * acciones + caja),
    )


def simular_oraculo(
    precios: pd.Series,
    acciones: int = 100,
    costos: CostModel | None = None,
    desde: pd.Timestamp | None = None,
) -> ResultadoSimulacion:
    """IMPOSIBLE DE EJECUTAR: compra en el mínimo real y vende en el máximo real.

    Esta función hace trampa a propósito. Mira toda la serie, encuentra el día
    más barato y el día más caro posterior, y opera ahí.

    Nadie puede hacer esto. Existe para una sola cosa: poner un techo al
    resultado. Cuando alguien dice "si compraba en el mínimo y vendía en el
    máximo ganaba X", ese X es este número, y es inalcanzable por definición,
    porque el mínimo solo se reconoce cuando ya pasó.

    La distancia entre este número y el de la estrategia real es la medida
    honesta de cuánto cuesta no ser adivino.
    """
    costo = costos or CostModel.us_equity()
    px = precios.dropna()
    if desde is not None:
        # El oráculo tampoco puede operar antes que las demás: si arrancara
        # primero, parte de su ventaja sería haber tenido más tiempo, no más
        # información.
        px = px.loc[desde:]

    # Mejor par comprar-después-vender: máximo de (max futuro / precio actual).
    maximo_futuro = px[::-1].cummax()[::-1]
    ratio = maximo_futuro / px
    fecha_compra = ratio.idxmax()
    posteriores = px.loc[fecha_compra:]
    fecha_venta = posteriores.idxmax()

    precio_compra, precio_venta = float(px.loc[fecha_compra]), float(px.loc[fecha_venta])

    # Mismo capital que las demás estrategias: el que hace falta para comprar la
    # posición objetivo el primer día del período común. La ventaja del oráculo
    # tiene que ser SOLO su información, no más plata ni más tiempo.
    capital = acciones * float(px.iloc[0])

    # Con timing perfecto ese capital compra más acciones, porque entra al
    # precio más bajo del período.
    acciones_compradas = capital / (precio_compra * (1.0 + costo.total_one_way))
    bruto_compra = acciones_compradas * precio_compra
    comision_compra = bruto_compra * costo.total_one_way

    bruto_venta = acciones_compradas * precio_venta
    comision_venta = bruto_venta * costo.total_one_way
    caja = capital - bruto_compra - comision_compra + bruto_venta - comision_venta

    transacciones = [
        Transaccion(fecha_compra, "COMPRA", acciones_compradas, precio_compra, bruto_compra,
                    comision_compra, -(bruto_compra + comision_compra), acciones_compradas,
                    capital - bruto_compra - comision_compra,
                    "MÍNIMO REAL (solo conocible a posteriori)"),
        Transaccion(fecha_venta, "VENTA", acciones_compradas, precio_venta, bruto_venta,
                    comision_venta, bruto_venta - comision_venta, 0.0, caja,
                    "MÁXIMO REAL (solo conocible a posteriori)"),
    ]

    return ResultadoSimulacion(
        nombre="ORÁCULO (imposible: requiere adivinar el futuro)",
        transacciones=transacciones,
        capital_inicial=capital,
        valor_final=caja,
        acciones_finales=0.0,
        caja_final=caja,
        dividendos_cobrados=0.0,
        costos_totales=comision_compra + comision_venta,
        precio_inicial=precio_compra,
        precio_final=float(px.iloc[-1]),
        fecha_inicio=px.index[0],
    )
