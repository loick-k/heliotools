from __future__ import annotations

GAS_REFERENCE_EXISTING_BOILER = "existing_boiler"
GAS_REFERENCE_RENEWAL = "boiler_renewal"

GAS_REFERENCE_CONTEXT_LABELS = {
    GAS_REFERENCE_EXISTING_BOILER: "Chaudière gaz existante",
    GAS_REFERENCE_RENEWAL: "Chaudière gaz à renouveler",
}

GAS_REFERENCE_CONTEXT_HELP = (
    "Chaudière gaz existante : la référence gaz intègre seulement le P1 gaz utile "
    "(prix gaz / rendement, avec inflation). Chaudière gaz à renouveler : la référence "
    "ajoute aussi les coûts fixes de chaudière gaz, P2 et P4."
)


def normalize_gas_reference_context(value: str | None) -> str:
    if value in GAS_REFERENCE_CONTEXT_LABELS:
        return str(value)
    if value in GAS_REFERENCE_CONTEXT_LABELS.values():
        for key, label in GAS_REFERENCE_CONTEXT_LABELS.items():
            if value == label:
                return key
    return GAS_REFERENCE_EXISTING_BOILER


def gas_reference_context_label(value: str | None) -> str:
    return GAS_REFERENCE_CONTEXT_LABELS[normalize_gas_reference_context(value)]


def includes_gas_boiler_fixed_costs(value: str | None) -> bool:
    return normalize_gas_reference_context(value) == GAS_REFERENCE_RENEWAL
