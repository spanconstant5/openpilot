# 2025 Corolla Hybrid LE identification record

This record describes the strongest identification that can currently be made
for the Span/`spanconstant5` 2025 Corolla Hybrid LE. It separates an exact ECU
identity from CAN traffic that is useful for topology and parser coverage but
is not unique enough for automatic vehicle selection.

## Decision

Keep StarPilot's manual selection for `TOYOTA_COROLLA_TSS3`. Do not register the
observed CAN census in Toyota `FINGERPRINTS` yet.

The exact target identity is the EPS application F181 response on physical
request `0x7A1`:

```text
02
8965F1208000 + 4 NUL bytes
8A3111213000 + 4 NUL bytes
```

The complete 33-byte response is:

```text
023839363546313230383030300000000038413331313132313330303000000000
```

This is verified by the retained firmware image, the application F181 producer,
the live diagnostic probe, and the successful 2026-09-13 patch/readback bundle.
The associated unit serial is `8965012N50E12H030731` and the MCU identity is
`R7F701383`.

The retained patch bundle is SHA-256
`228d7623620db8f9543626eadfef547eb471dc26f8e33c97ee42622d9f081a8a`.
Its target-sector final readback is
`272f303f877702b339ed7d9cfd1700888829a147ce6d89102d1b27610b9938f3`
and its CRC-sector final readback is
`d16ec27e5aff169becf52a8f48146601f3cb564188d9410fe5622312784f3ace`.
Those readbacks match the generated candidates exactly.

The trim name "Hybrid LE" is useful documentation, but there is no evidence
that LE has a distinct openpilot control contract or a unique CAN fingerprint.
The platform identity should therefore remain Corolla Hybrid 2025 TSS 3.0.

## Recorded CAN candidates

Two supplied full rlogs converge on the same 22-entry logical-bus-0 ADAS set:

```text
020:12 123:16 160:32
180:64 181:64 182:64 183:64 184:64 185:64
186:64 187:64 188:64 189:64 18A:64 18B:64
18C:48 1A0:48 200:64 201:64 230:64 440:32 450:32
```

They contain 47,711 eligible bus-0 frames. Processing the later segment second
adds no address. Logical bus 1 converges on the 152-entry set retained in
`opendbc/car/toyota/tss3_census.py`, with 159,072 eligible frames. The source
files are pinned by these SHA-256 values:

```text
segment 0 compressed: 7d51da944ee0bdcedbd5a7ecf72c3a9908b8bc8634cfe6e23638c447cb41b4c7
segment 10 raw:        98710e8d23a40796718b7be566efc83a569be90ece59b5d7f70377143e38338b
```

Both logs contain a valid target-car VIN and model-year code `S` (2025). The
full VIN is deliberately omitted from this public-source record. Their embedded
`carParams` remains `MOCK`, and the three recorded `carFw` entries are zero-like
responses from HVAC, camera, and radar. They do not contain a usable EPS F181
response and must not be entered into `FW_VERSIONS`.

## Why FPv1 remains blocked

The retained exact Camry TSS3 census contains 179 address/DLC pairs and the
Corolla powertrain census is a strict subset. FPv1 eliminates candidates as
messages arrive; a strict subset can therefore leave the Corolla candidate
alive while the Camry is still starting, making the result timing-dependent.
The 22-entry ADAS set is also TSS3 network geometry rather than a proved
Corolla-only signature.

Adding either candidate to `FINGERPRINTS` would turn good census evidence into
an unsafe identity claim. The current test intentionally checks that
`CAR.TOYOTA_COROLLA_TSS3` is absent from that table.

## Path to automatic selection

Automatic selection needs one of these evidence-backed inputs:

1. Read the exact EPS F181 through the already-proved `(bus 1, param 1)` route,
   then require the complete two-record response above.
2. Obtain a standard startup-visible set of exact F181 responses from several
   essential ECUs that uniquely distinguishes this platform. FRC and Brake
   identities are especially useful if they are reachable without changing ECU
   state.
3. Establish a Corolla-only CAN discriminator using multiple independently
   identified 2025 Corolla and Camry captures. The current strict-subset census
   does not provide one.

The first option is the shortest known route, but it is not implemented in the
normal StarPilot startup query. Adding a global Toyota bus-1 diagnostic request
before the platform is known would affect other Toyota vehicles, so it should
not be introduced without a target-scoped query design and offline tests.

## Current operating consequence

Select `Toyota Corolla Hybrid 2025 (TSS 3.0)` and enable StarPilot's manual
fingerprint override. This selects the dedicated parser/controller while
avoiding a timing-dependent automatic match. The startup helper now reloads
both persisted values before interface selection, so a stale serialized `MOCK`
snapshot cannot discard the manual choice. The successful EPS patch evidence
does not by itself validate StarPilot engagement, lateral control, longitudinal
control, tuning, or Panda firmware compatibility.
