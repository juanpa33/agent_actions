"""Modelo impositivo configurable para la simulación.

ADVERTENCIA QUE NO ES FORMALIDAD: esto NO es asesoramiento fiscal. Las alícuotas
por defecto se transcribieron de fuentes públicas secundarias y las reglas
cambian con frecuencia. Verificá cada valor con tu contador antes de tomar
cualquier decisión. El objetivo de este módulo no es calcularte la declaración
jurada: es mostrar cómo los impuestos cambian el ranking entre estrategias.

El efecto estructural que hay que entender, y que es independiente de la
alícuota exacta:

    El impuesto a la ganancia se paga cuando VENDÉS, no mientras mantenés.

Eso significa que cada venta adelanta un pago que podrías haber postergado, y
la plata que se va en ese pago deja de componer. Una estrategia que opera mucho
paga impuestos antes y más veces que una que mantiene, aunque ambas terminen
con la misma ganancia bruta. Esto es matemática, no opinión, y se puede medir:
la simulación lo hace.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class TaxModel:
    """Alícuotas aplicables. TODAS deben verificarse con un contador."""

    nombre: str
    capital_gains_rate: float = 0.0
    """Impuesto sobre la ganancia realizada al vender."""

    dividend_withholding_rate: float = 0.0
    """Retención en el país de origen, antes de que la plata llegue a tu cuenta."""

    dividend_local_rate: float = 0.0
    """Impuesto local sobre el dividendo, adicional a la retención de origen."""

    wealth_tax_rate: float = 0.0
    """Impuesto anual sobre la tenencia (tipo Bienes Personales), aplicado al 31/12."""

    fuente: str = ""
    advertencia: str = "Verificá estas alícuotas con tu contador antes de operar."

    @classmethod
    def sin_impuestos(cls) -> "TaxModel":
        """Referencia para aislar el efecto impositivo del resto."""
        return cls(nombre="Sin impuestos (referencia teórica)", fuente="—",
                   advertencia="Escenario irreal, útil solo para comparar.")

    @classmethod
    def adr_o_accion_extranjera(cls) -> "TaxModel":
        """Residente argentino operando ADR o acción extranjera directa.

        Valores de referencia consultados en septiembre de 2026:
          - 15% sobre la ganancia por venta de acciones extranjeras y ADR.
          - 30% de retención estadounidense sobre dividendos. Argentina y EE.UU.
            firmaron un acuerdo fiscal en 1981 que el Senado estadounidense nunca
            ratificó, así que no hay tratado vigente y no aplica alícuota reducida.
          - Bienes Personales sobre activos en el exterior.
        """
        return cls(
            nombre="ADR / acción extranjera (residente argentino)",
            capital_gains_rate=0.15,
            dividend_withholding_rate=0.30,
            dividend_local_rate=0.0,
            wealth_tax_rate=0.0125,
            fuente="Guías públicas de tributación consultadas en 09/2026",
        )

    @classmethod
    def cedear(cls) -> "TaxModel":
        """Residente argentino operando CEDEAR.

        La diferencia con el ADR es estructural y grande: la ganancia por venta
        de CEDEAR estaría EXENTA del impuesto a las ganancias, mientras que la
        del ADR tributa 15%. Para una estrategia que vende seguido, el
        instrumento puede pesar más que la táctica.
        """
        return cls(
            nombre="CEDEAR (residente argentino)",
            capital_gains_rate=0.0,
            dividend_withholding_rate=0.30,
            dividend_local_rate=0.07,
            wealth_tax_rate=0.0125,
            fuente="Guías públicas de tributación consultadas en 09/2026",
        )

    @classmethod
    def accion_local_byma(cls) -> "TaxModel":
        """Acción argentina con oferta pública en BYMA.

        Las alícuotas por defecto quedan en cero porque el tratamiento de las
        acciones locales con oferta pública para personas humanas residentes
        NO fue verificado para este proyecto. Poner cero es explícito: significa
        "falta el dato", no "no paga".
        """
        return cls(
            nombre="Acción local BYMA (SIN VERIFICAR)",
            capital_gains_rate=0.0,
            dividend_withholding_rate=0.0,
            dividend_local_rate=0.0,
            wealth_tax_rate=0.0,
            fuente="NO VERIFICADO",
            advertencia=(
                "ALÍCUOTAS NO VERIFICADAS. Están en cero porque falta el dato, "
                "no porque el instrumento esté exento. Consultá a tu contador "
                "antes de usar este escenario para decidir."
            ),
        )

    def resumen(self) -> str:
        return (
            f"{self.nombre}\n"
            f"  Ganancia por venta:       {self.capital_gains_rate * 100:.2f}%\n"
            f"  Retención en origen:      {self.dividend_withholding_rate * 100:.2f}%\n"
            f"  Impuesto local dividendo: {self.dividend_local_rate * 100:.2f}%\n"
            f"  Tenencia anual:           {self.wealth_tax_rate * 100:.2f}%\n"
            f"  Fuente: {self.fuente}\n"
            f"  {self.advertencia}"
        )


@dataclass
class Lote:
    """Un paquete de acciones compradas en una fecha a un precio."""

    fecha: pd.Timestamp
    acciones: float
    precio: float


@dataclass
class RegistroFiscal:
    """Seguimiento del costo de cada acción, para calcular la ganancia realizada.

    Usa FIFO: se venden primero las acciones compradas primero. Es el criterio
    más habitual y el que suelen aplicar los agentes por defecto. Si tu comitente
    usa otro (costo promedio, por ejemplo), el impuesto de cada venta cambia,
    aunque el total a lo largo de toda la vida de la posición sea el mismo.
    """

    lotes: deque[Lote] = field(default_factory=deque)
    ganancia_realizada_acumulada: float = 0.0
    impuestos_pagados: float = 0.0

    def comprar(self, fecha: pd.Timestamp, acciones: float, precio: float) -> None:
        self.lotes.append(Lote(fecha, acciones, precio))

    def vender(self, acciones: float, precio: float) -> tuple[float, float]:
        """Consume lotes por FIFO. Devuelve (ganancia_realizada, costo_base)."""
        restantes = acciones
        costo_base = 0.0

        while restantes > 1e-9 and self.lotes:
            lote = self.lotes[0]
            usar = min(restantes, lote.acciones)
            costo_base += usar * lote.precio
            lote.acciones -= usar
            restantes -= usar
            if lote.acciones <= 1e-9:
                self.lotes.popleft()

        ganancia = acciones * precio - costo_base
        self.ganancia_realizada_acumulada += ganancia
        return ganancia, costo_base

    @property
    def acciones_en_cartera(self) -> float:
        return sum(lote.acciones for lote in self.lotes)

    def ganancia_no_realizada(self, precio_actual: float) -> float:
        """Ganancia latente: la que todavía no pagó impuestos porque no se vendió."""
        return sum(
            lote.acciones * (precio_actual - lote.precio) for lote in self.lotes
        )


def impuesto_por_venta(ganancia: float, modelo: TaxModel) -> float:
    """Impuesto de una venta. Una pérdida no genera impuesto negativo.

    Simplificación deliberada: no se modela el cómputo de quebrantos contra
    ganancias futuras, que en la práctica existe y reduce el impuesto. Por lo
    tanto este cálculo SOBREESTIMA levemente la carga de una estrategia con
    ventas perdedoras. Se prefiere errar por exceso de prudencia.
    """
    return max(ganancia, 0.0) * modelo.capital_gains_rate


def dividendo_neto(bruto: float, modelo: TaxModel) -> tuple[float, float]:
    """Dividendo que efectivamente llega a la cuenta. Devuelve (neto, impuesto).

    Primero se aplica la retención del país de origen, y el impuesto local se
    calcula sobre el bruto. Sin tratado vigente entre Argentina y EE.UU. no hay
    crédito automático por la retención, de modo que ambas cargas se acumulan.
    """
    retencion = bruto * modelo.dividend_withholding_rate
    local = bruto * modelo.dividend_local_rate
    impuesto = retencion + local
    return bruto - impuesto, impuesto


def impuesto_patrimonial(valor_cartera: float, modelo: TaxModel) -> float:
    """Impuesto anual sobre la tenencia, aplicado al cierre del año.

    No se modela el mínimo no imponible, que en la práctica exime a carteras
    chicas. Para posiciones por debajo de ese mínimo, este cálculo sobreestima.
    """
    return max(valor_cartera, 0.0) * modelo.wealth_tax_rate
