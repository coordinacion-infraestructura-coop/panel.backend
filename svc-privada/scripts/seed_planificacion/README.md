# Carga inicial de planificación: Cordón Cuneta (pestaña GENERAL)

Emparejamiento de la planilla del área con el padrón oficial de localidades
(`id_geo`, ADR-024/026), como insumo de la Fase 5 de
`docs/files/spec-privada-planificacion-programas.md` (draft). Generado el 2026-11-19.
Todavía **no carga nada**: es el CSV que el script de carga va a leer después de
que una persona revise los casos dudosos.

- Fuente: Google Drive `1PRSBQ5xOl3Oms42PkHMHx8prF5DAYSdm` ("Cordón Cuneta OK.xlsx"), solo la pestaña `GENERAL`. La planilla no se modificó.
- Salida: `cordon_cuneta_general.csv` (UTF-8 con BOM, para que Excel lo abra bien). Una fila por cada fila de la planilla; `fila_origen` es el número de fila en Excel.
- Script: `emparejar_cordon_cuneta.py <xlsx> <raíz del repo> <dir salida> <resumen.json>`, que se corre con `python -I`.

## Padrón usado y cobertura

No se consultó producción. El padrón se armó a partir del repo:

1. `docs/data/geo_localidades.json`: 544 filas. Es el seed de la migración `0008`; la `0035` confirma que el padrón de producción tenía esas 544 filas al 2026-10-07.
2. `0033`: desactiva 7 duplicados (555, 43, 81, 285, 78, 213, 212). Quedan **537 activas**.
3. `0035`: pasa los nombres a mayúsculas. No cambia el matching.
4. `0042`: da de alta `SANTIAGO TEMPLE` (Río Segundo) y `KILÓMETRO 658` (Río Primero). El `id_geo` **se calcula al correr la migración** (`max+1`), así que no figura en el repo. Lo más probable es que sean 561 y 562, pero no se usan como match firme.
5. Alias de `viv_geo_alias_manual`: los de `app/geo/seed_data.py` (17 + 2 + 6 + 19) y los 3 "confirmado sin vínculo" de la `0036`. La tabla `VINCULACION_MANUAL` de `AtpPage.tsx` **ya no está en el frontend**. Sus 17 vínculos son el primer bloque de `seed_data.py`, así que quedaron incluidos.

**Lo que puede faltar**: alias cargados a mano desde la pantalla "Localidades sin resolver" (ADR-026), que solo existen en la base de producción. Tampoco se pudo confirmar el `id_geo` real de las 2 altas de la `0042`.

## Reglas de matcheo

Todo se busca dentro del mismo departamento. La planilla trae `COLON`/`COLÓN`, `GENERAL ROCA`/`GRAL. ROCA`, `ROQUE SAENZ PEÑA` ↔ `PTE ROQUE SAENZ PEÑA`, etc., y los 26 departamentos se mapearon bien.
Se replica `app/geo/matching.py`: `normalize_name`, `normalize_departamento` y `candidatos_localidad`, este último aplicado tanto a la fuente como al padrón, igual que `_cargar_padron`.

| método | criterio |
|---|---|
| `exacto` | El nombre normalizado coincide. También cuenta si coincide después de quitar la puntuación, expandir abreviaturas (`Va.`/`Va`/`V.` → Villa, `Sta.` → Santa, `Gral.` → General, `EST.` → Estación, `COL.` → Colonia, `ARG.` → Argentinas, `4` → cuatro), sacar un paréntesis sobrante o separar por guion. Cuando hubo una de esas transformaciones, se anota en `nota_match`. |
| `alias` | Coincide con un alias de `viv_geo_alias_manual` que apunta al mismo departamento. |
| `fuzzy` | Similitud ≥ 90 con un único candidato claro (≥ 10 puntos sobre el segundo), contra el padrón o contra el texto de un alias. |
| `revisar` | Similitud entre 60 y 89, o un caso que no se puede resolver solo con el repo. **No lleva `id_geo`**. Los candidatos están en la columna `candidatos`. |
| `sin_match` | Ningún candidato razonable. |

Columnas agregadas al pedido: `monto_nota` (valores tipo `150M`, que no se convierten), `col_extra_2` (columna M, sin título, que traen solo 8 filas), `nota_match` y `candidatos`.
Los números se normalizan: `2,743` → 2743, `200,000,000` → 200000000, `1.0` → 1. Los textos (`SI`, `NO`, `PARA FIRMA`, `ATP`…) quedan tal cual.

## Conteos

424 filas de datos. Se descartó 1 fila basura: la 428, con la URL `https://gestorcooperativo.web.app/`.

| método | filas |
|---|---|
| exacto | 397 (17 de ellas después de normalizar abreviaturas o puntuación) |
| alias | 18 |
| fuzzy | 6 |
| revisar | 3 |
| sin_match | 0 |

**No hay duplicados**: ningún `id_geo` aparece dos veces. Los nombres que se repiten en la planilla están en departamentos distintos (LOS CHAÑARITOS en Cruz del Eje 539 y en Río Segundo 232; VILLA SARMIENTO (C) en Gral. Roca 60 y (M) en San Alberto 253) y quedaron bien separados.

## A revisar (sin `id_geo` en el CSV)

| fila | depto | planilla | candidatos | sugerencia |
|---|---|---|---|---|
| 23 | Calamuchita | PARQUE CALMAYO | 2 CALMAYO (67) | Probablemente 2: CALMAYO no aparece en ninguna otra fila de la planilla. Hay que confirmar si "Parque Calmayo" es la misma comuna. |
| 239 | Río Primero | VILLA Sta. ROSA DE RIO I | 208 VILLA SANTA ROSA (78) | Probablemente 208, que no aparece en ninguna otra fila. **Ojo**: el alias de la `0034` `SANTA ROSA DE RIO PRIMERO` → 206 "RIO PRIMERO" (marcado como de confianza media) choca con esto. La 206 ya está tomada por la fila 237 `RIO PRIMERO`, y Villa Santa Rosa de Río Primero y Río Primero son dos localidades distintas. Conviene revisar ese alias. |
| 264 | Río Segundo | SANTIAGO TEMPLE | alta de la `0042`, `id_geo` probable 561 | Confirmar el `id_geo` real en la base, o tomarlo de `priv_geo_localidades` cuando la carga corra contra el espejo. |

## Fuzzy (con `id_geo`, conviene una mirada rápida)

| fila | depto | planilla | padrón | score |
|---|---|---|---|---|
| 153 | Roque Sáenz Peña | RIOBAMBA | 133 RIO BAMBA | 94 |
| 154 | Pocho | SAN JERONIMO | 548 SAN GERÓNIMO | 92 |
| 185 | Punilla | VILLA CAROS PAZ | 155 VILLA CARLOS PAZ | 97 |
| 296 | San Justo | MIRAMAR DE ANZENUZA | 289 MIRAMAR (por el alias "Miramar de Ansenuza") | 95 |
| 352 | Santa María | BOUWER | 303 BOWER | 91 |
| 394 | Tulumba | ROSARIO DE SALADILLO | 559 ROSARIO DEL SALADILLO | 98 |

## Otros puntos a confirmar

- **Fila 251, `Va. CANDELARIA NORTE` → 220 VILLA CANDELARIA (alias)**. El alias de la `0034` está marcado como de confianza media.
- **Fila 226, `PEDRO E. VIVAS (KM. 658)` → 195 (exacto)**. La migración `0042` agregó además una fila `KILÓMETRO 658` en Río Primero, que puede ser un **duplicado dentro del padrón** de la 195.
- **Fila 132, `CORRAL DE BUSTOS-IFFLINGER` → 107 CORRAL DE BUSTOS** (separado por guion) y **fila 187, `Sta. CATALINA - HOLMBERG` → 182 SANTA CATALINA (EST. HOLMBERG)**. Quedaron como `exacto` con nota.
- **En el padrón, 241 "AGUA DE ORO" figura en Río Segundo** y 22 "AGUA DE ORO" en Colón. La planilla (Colón) tomó la 22. La 241 parece un error del padrón.
- **Las celdas `150M`/`200M`/`50M`** de "MONTO FIRMADO O SUGERIDO" (filas 283, 285, 288, 289, 306, todas de San Justo) quedaron en `monto_nota`, sin convertir.
- **La columna L (sin título)** parece repetir el grupo de color en Calamuchita, Cruz del Eje, Gral. San Martín e Ischilín, aunque la prioridad (columna B) esté vacía. **La columna M** trae montos o saldos de ATP en las filas 94–96 y 136–140. Las dos se copiaron tal cual en `col_extra` / `col_extra_2`.
- **Cobertura**: la planilla cubre 421 de las 537 localidades activas del padrón. La spec habla de "~551"; con el repo actual da 537 activas + 2 altas de la `0042`.

## Localidades del padrón que no aparecen en la planilla: 116

| departamento | n | localidades (id_geo) |
|---|---|---|
| CALAMUCHITA | 6 | ARROYO DE SAN ANTONIO (382), ATHOS PAMPA (385), CALMAYO (2), CERRO DE SAN LORENZO (SALTO DE TOLEDO) (386), SOCONCHO (LAS BAJADAS) (387), VILLA SANTA MONICA (384) |
| CAPITAL | 1 | CORDOBA (21) |
| COLÓN | 13 | ASCOCHINGA (391), BLAS DE ROSALES (394), CUATRO HOJAS (390), EL DIQUESITO (396), EL PUEBLITO (393), GUIÑAZU (389), LA PUERTA (395), NUÑEZ DEL PRADO (399), SAN CARLOS DE ASCOCHINGA (402), TEJEDA (398), VILLA COLANCHANGA (400), VILLA CORAZON DE MARIA (401), VILLA LOS LLANOS (388) |
| CRUZ DEL EJE | 3 | CHARACATO (403), LOS SAUCES (SAN MARCOS) (405), PICHANAS (404) |
| GRAL ROCA | 3 | DE LA SERNA (408), LECUEDER (406), VILLA MODERNA (407) |
| GRAL SAN MARTÍN | 4 | CAYUQUEO (410), LAS MOJARRAS (411), SANABRIA (409), SANTA VICTORIA (412) |
| ISCHILÍN | 9 | CERRO NEGRO (421), HUASCHA (420), ISCHILIN (422), ISCHILIN VIEJO (417), JAIME PETER (418), LOS CADILLOS (419), SAN PEDRO DE TOYOS (413), VILLA ALBERTINA (414), VILLA COLIMBA (416) |
| JUÁREZ CELMAN | 3 | CARNERILLO (87), OLMOS (VILLA FELIPA) (433), PEDRO E. FUNES (434) |
| MARCOS JUAREZ | 2 | COLONIA VEINTICINCO (RIO III) (437), SAN JOSE DEL SALTEÑO (436) |
| POCHO | 2 | ALTO DEL TALA (439), TANINGA (438) |
| PTE ROQUE SAENZ PEÑA | 3 | CURAPALIGUE (440), GUARDIA VIEJA (441), RUIZ DIAZ DE GUZMAN (442) |
| PUNILLA | 10 | COPINA (430), EL DURAZNO (426), LOS GIGANTES (425), LOS PAREDONES (SANTA ISABEL) (428), MALLIN (423), MOLINARI (424), PIEDRAS GRANDES (431), QUEBRADA DE LUNA (429), SAN JOSE (432), VILLA INDEPENDENCIA (427) |
| RIO SECO | 1 | LA ESTANCIA (470) |
| RÍO CUARTO | 17 | CUATRO VIENTOS (448), ESPINILLOS (449), GENERAL PAUNERO (450), GENERAL SOLER (451), LA AGUADA (452), LA BARRANQUITA (446), LA BRIANZA (453), LA GILDA (444), LAS GAMAS (454), LOS JOTES (455), PASO DE RIO SECO (456), PASO DEL DURAZNO (443), PUEYRREDON (457), PUNTA DEL AGUA (458), SAN AMBROSIO (459), SANTA RITA (460), TRES POZOS (461) |
| RÍO PRIMERO | 9 | CAÑADA HONDA (462), ESTACION MERCEDES (205), KILOMETRO 691 (465), MONTE DEL ROSARIO (464), NUEVA ANDALUCIA (466), POZO DE LA LOMA (467), RANGEL (468), TALA NORTE (EL ALCALDE) (463), VILLA SANTA ROSA (208) |
| RÍO SEGUNDO | 1 | AGUA DE ORO (241) |
| SAN ALBERTO | 3 | LAS MARAVILLAS (473), SAN HUBERTO (472), VILLA INTICO (474) |
| SAN JAVIER | 2 | EL CARRIZAL (475), QUEBRADA DE LOS POZOS (476) |
| SAN JUSTO | 14 | COLONIA 10 DE JULIO (477), COLONIA GENERAL DEHEZA (485), COLONIA LA COYUNDA (271), COLONIA LUIS A. SAUZE (479), COLONIA MALBERTINA (481), COLONIA SANTA MARIA (491), EL FUERTECITO (478), JERONIMO CORTES (482), LA CURVA (483), MONTE REDONDO (480), PLAYA GRANDE (490), PLAZA GENERAL DEHEZA (486), SAN ANTONIO (492), TRINCHERA (487) |
| SANTA MARÍA | 5 | COSME (496), JOSE DE LA QUINTANA (497), SIERRAS DE ORO (495), VILLA SAN NICOLAS (493), YOCSINA (494) |
| TERCERO ARRIBA | 1 | SALTO NORTE (500) |
| TOTORAL | 2 | EL TALITA (VILLA GUTIERREZ) (502), TOTORAL GRANDE (501) |
| UNIÓN | 2 | RAMON J. CARCANO (504), SAN SEVERO (505) |

Esta lista incluye CALMAYO (2) y VILLA SANTA ROSA (208), que son los candidatos de las filas 23 y 239. Si se confirman, la lista baja a 114. Las 2 altas de la `0042` no están en la lista porque su `id_geo` no está en el repo: SANTIAGO TEMPLE corresponde a la fila 264, y KILÓMETRO 658 no tiene fila (ver el posible duplicado con la 195).

## Correcciones confirmadas por el usuario (2026-11-19)

- Fila 23, PARQUE CALMAYO → 2 CALMAYO (`metodo=confirmado_usuario`).
- Fila 239, VILLA Sta. ROSA DE RIO I → 208 VILLA SANTA ROSA (`metodo=confirmado_usuario`). El alias de la migración 0034 que la mandaba a 206 es incorrecto; se corrige aparte en svc-vivienda.
- Los 6 matcheos por parecido del nombre quedan confirmados.
- Montos "150M" / "200M" / "50M" = millones de pesos. Ya están convertidos en `monto_firmado_o_sugerido`.
- **Toda la columna MONTO FIRMADO O SUGERIDO está en millones** (`200` = $200.000.000). El script de carga multiplica por 1.000.000 todo valor menor a 100.000. MONTO ya viene en pesos.
- AGUA DE ORO es de Colón (22). El 241 en Río Segundo es un error del padrón y se corrige aparte.
- Pendiente: fila 264, SANTIAGO TEMPLE. Su `id_geo` se toma de `priv_geo_localidades` al cargar.


---

# Córdoba Hogar (planilla "Cordoba Hogar OK.xlsx")

Generado el 2026-11-19, con el mismo criterio que Cordón Cuneta. Todavía **no carga nada**.

- Fuente: `Cordoba Hogar OK.xlsx`, bajada como .xlsx (spec §12.5). La planilla no se modificó: se leyó una copia.
- Salida: `cordoba_hogar_general.csv` (UTF-8 con BOM). Una fila por cada fila de la planilla; `fila_origen` es el número de fila en Excel.
- Script: `emparejar_cordoba_hogar.py <xlsx> <raíz del repo> <dir salida> <resumen.json>`, con `python -I`. El resolver (padrón, alias, exacto → alias → fuzzy) es **copia literal** del de CC. Lo único nuevo es la lectura de la planilla y las correcciones confirmadas por el usuario (`CONFIRMADOS`, `forzar_revisar`, regla de Agua de Oro). `emparejar_cordon_cuneta.py` no se tocó.
- El padrón y los alias son los mismos que se usaron para CC: 537 localidades activas y 48 alias. No se consultó producción.

## Relevamiento de la planilla

**Pestañas**: hay una sola, `Hoja 1`, y es la general: todas las localidades agrupadas por departamento. No hay pestañas de colores ni por departamento como en CC.

**Estructura**: la fila 1 está vacía, el encabezado está en la fila 2 y los datos van de la fila 3 a la 451. El departamento aparece solo en la primera fila de cada bloque (de Minas en adelante, con celdas combinadas) y casi siempre con un espacio adelante (`' CALAMUCHITA'`). Los bloques están separados por una fila en blanco, salvo entre Gral. San Martín e Ischilín. No hay filas ni columnas ocultas, ni comentarios, validaciones o formatos condicionales. Tampoco hay nada a la derecha de la columna J ni debajo de la fila 451 (aunque `max_row` diga 1423).

**Filas basura**: no hay. Las 23 filas vacías son separadores y se saltean. Quedan **426 filas de datos** en 25 departamentos. Capital no está.

| col | encabezado | contenido |
|---|---|---|
| A | DEPARTAMENTO | Solo en la primera fila del bloque. Se arrastra hacia abajo |
| B | LOCALIDAD | Texto libre con abreviaturas (`Va.`, `V.`, `Sta.`, `Gral.`) |
| C | TIPO | `M` 258 · `C` 168 |
| D | HAB | Número entero (float en Excel). 3 valores difieren de CC: Estación Juárez Celman trae 2743, una copia del valor de Estación Gral. Paz (en CC figura 13509); Buchardo 1960 contra 1950; Tío Pujio 3659 contra 3559 |
| E | VISITA DELGOBERNADOR | `SI ANTERIOR` 173 · `SI` 145 · `NO` 108 |
| F | ANUNCIO DEL GOBERNADOR | `NO` 340 · `SI` 86 |
| G | CONVENIO DE VIVIENDA | `SI` 285 · `NO` 141 |
| H | REF EN EL GESTOR | Un solo valor: `3` en Los Molinos (fila 7) |
| I | CANTIDAD DE VIVIENDAS | **Vacía** en todas las filas |
| J | OBSERVACIÓN | **Vacía** en todas las filas |

**Prioridad**: no hay una columna de prioridad. Se expresa con el **color de relleno de la fila**. En las filas 3 a 294 el color cubre B:J. Desde la 295 cubre solo B:D. Los colores que aparecen:

| color (hex) | filas | prioridad propuesta (escala de la spec §4.3) |
|---|---|---|
| celeste `00B0F0` | 288 | 1 |
| verde `92D050` | 50 | 2 |
| naranja `FFC000` | 12 | 3 |
| amarillo `FFFF00` | 8 | 4 |
| rojo `FF0000` | 60 | 5 |
| violeta `674EA7` | 7 | **? (a confirmar)**: Colonia Anita, Colonia Iturraspe, Colonia Marina, Colonia Prosperidad y Porteña (San Justo), Anisacate (Santa María) y San Francisco del Chañar (Sobremonte). Solo B:C están en violeta. La celda HAB conserva otro color debajo: rojo en 6 de ellas y amarillo en San Francisco del Chañar. Parece una marca puesta encima de la prioridad. Todas tienen convenio `NO` |
| gris `CCCCCC` | 1 | **? (probable X desestimado)**: Villa Cerro Azul (Colón). En CC es `X` |

El CSV trae `prioridad_color`, `prioridad_color_hex`, `prioridad_propuesta` y `color_hab` (solo cuando el color de HAB difiere del de la fila).
Cruces útiles: el color **no coincide** con la prioridad de CC para la misma localidad. Por ejemplo, de las celestes de CH, 86 son 1 en CC, pero 169 no tienen prioridad en CC. Esto es coherente con que la prioridad sea por programa. Además, el celeste coincide casi siempre con `CONVENIO = SI` (275 de 288) y el rojo con `NO` (59 de 60). **Hay que confirmar con el área** si los colores de CH significan lo mismo que la escala 1–5 de CC.

**Montos**: la planilla de CH **no tiene columnas de monto**, así que la regla "150M = 150.000.000" no aplica. El script la soporta igual por si aparecen más adelante.

## Conteos

| método | filas |
|---|---|
| exacto | 398 (13 después de expandir abreviaturas o quitar puntuación, con la nota en `nota_match`) |
| alias | 18 |
| fuzzy | 4 (los tres confirmados en CC, más Miramar de Anzenuza por alias) |
| confirmado_usuario | 2 (Parque Calmayo → 2; Villa Sta. Rosa de Río I → 208) |
| revisar | 4 |
| sin_match | 0 |

Agua de Oro (fila 28, Colón) → 22, exacto. El script además manda a `revisar` cualquier match a 241.

**Duplicados**: no hay. Ningún `id_geo` se repite. Los nombres repetidos están en departamentos distintos y quedaron separados: Los Chañaritos (Cruz del Eje 539 / Río Segundo 232) y Villa Sarmiento (C) (Gral. Roca 60) / (M) (San Alberto 253).

**Contra CC**: CH cubre las mismas localidades que CC, más CARNERILLO (87) y la fila de Paso del Durazno. Los `id_geo` coinciden en todas las localidades en común, salvo Pedro E. Vivas, que acá se manda a revisar a propósito.

## A revisar (sin `id_geo` en el CSV)

| fila | depto | planilla | candidatos | sugerencia |
|---|---|---|---|---|
| 121 | Juárez Celman | PASO DEL DURAZNO | 443 PASO DEL DURAZNO (**Río Cuarto**) | El alias de `seed_data.py` ya documenta este caso ("límite departamental: el Sheet decía Juárez Celman, el padrón real es Río Cuarto"). Probablemente 443. Como cruza de departamento, el script no lo asume |
| 244 | Río Primero | PEDRO E. VIVAS (KM. 658) | 195 PEDRO E. VIVAS (KM. 658) (exacto) · 562? KILÓMETRO 658 (alta 0042) | Va a revisión manual por indicación del usuario (posible duplicado del padrón). En CC quedó como 195 |
| 288 | Río Segundo | SANTIAGO TEMPLE | 561? SANTIAGO TEMPLE (alta 0042) | Igual que en CC: tomar el `id_geo` de `priv_geo_localidades` al cargar |
| 419 | Tulumba | VILLA DEL ROSARIO DEL SALADILLO | 559 ROSARIO DEL SALADILLO (81) · 350 LUCIO V. MANSILLA (55) · 353 SAN JOSE DE LAS SALINAS (48) | Probablemente 559. Es la misma localidad que en CC se escribió "Rosario de Saladillo" (confirmada), con el nombre largo. No aparece otra fila con 559 |

## Fuzzy (con `id_geo`)

| fila | depto | planilla | padrón | score |
|---|---|---|---|---|
| 159 | Pocho | SAN JERONIMO | 548 SAN GERÓNIMO | 92 (confirmado en CC) |
| 167 | Roque Sáenz Peña | RIOBAMBA | 133 RIO BAMBA | 94 (confirmado en CC) |
| 342 | San Justo | MIRAMAR DE ANZENUZA | 289 MIRAMAR (por el alias "Miramar de Ansenuza") | 95 (igual que en CC) |
| 357 | Santa María | BOUWER | 303 BOWER | 91 (confirmado en CC) |

Los 18 matcheos por alias son exactamente los mismos 18 `id_geo` que en CC. Hay que revisar los de confianza media: **266 Va. CANDELARIA NORTE → 220** (como en CC) y **22 LAS BAJADAS → 7** (el padrón tiene además 387 SOCONCHO (LAS BAJADAS) en el mismo departamento; se toma el nombre literal, según el alias de la `0034`).

## Localidades del padrón que no aparecen en la planilla: 115

La lista incluye 443, 195 y 559, que son los candidatos de las filas 121, 244 y 419. Si se confirman, baja a 112. CALMAYO (2) y VILLA SANTA ROSA (208) ya están cubiertas por las confirmaciones.

| departamento | n | localidades (id_geo) |
|---|---|---|
| CALAMUCHITA | 5 | ARROYO DE SAN ANTONIO (382), ATHOS PAMPA (385), CERRO DE SAN LORENZO (SALTO DE TOLEDO) (386), SOCONCHO (LAS BAJADAS) (387), VILLA SANTA MONICA (384) |
| CAPITAL | 1 | CORDOBA (21) |
| COLÓN | 13 | ASCOCHINGA (391), BLAS DE ROSALES (394), CUATRO HOJAS (390), EL DIQUESITO (396), EL PUEBLITO (393), GUIÑAZU (389), LA PUERTA (395), NUÑEZ DEL PRADO (399), SAN CARLOS DE ASCOCHINGA (402), TEJEDA (398), VILLA COLANCHANGA (400), VILLA CORAZON DE MARIA (401), VILLA LOS LLANOS (388) |
| CRUZ DEL EJE | 3 | CHARACATO (403), LOS SAUCES (SAN MARCOS) (405), PICHANAS (404) |
| GRAL ROCA | 3 | DE LA SERNA (408), LECUEDER (406), VILLA MODERNA (407) |
| GRAL SAN MARTÍN | 4 | CAYUQUEO (410), LAS MOJARRAS (411), SANABRIA (409), SANTA VICTORIA (412) |
| ISCHILÍN | 9 | CERRO NEGRO (421), HUASCHA (420), ISCHILIN (422), ISCHILIN VIEJO (417), JAIME PETER (418), LOS CADILLOS (419), SAN PEDRO DE TOYOS (413), VILLA ALBERTINA (414), VILLA COLIMBA (416) |
| JUÁREZ CELMAN | 2 | OLMOS (VILLA FELIPA) (433), PEDRO E. FUNES (434) |
| MARCOS JUAREZ | 2 | COLONIA VEINTICINCO (RIO III) (437), SAN JOSE DEL SALTEÑO (436) |
| POCHO | 2 | ALTO DEL TALA (439), TANINGA (438) |
| PTE ROQUE SAENZ PEÑA | 3 | CURAPALIGUE (440), GUARDIA VIEJA (441), RUIZ DIAZ DE GUZMAN (442) |
| PUNILLA | 10 | COPINA (430), EL DURAZNO (426), LOS GIGANTES (425), LOS PAREDONES (SANTA ISABEL) (428), MALLIN (423), MOLINARI (424), PIEDRAS GRANDES (431), QUEBRADA DE LUNA (429), SAN JOSE (432), VILLA INDEPENDENCIA (427) |
| RIO SECO | 1 | LA ESTANCIA (470) |
| RÍO CUARTO | 17 | CUATRO VIENTOS (448), ESPINILLOS (449), GENERAL PAUNERO (450), GENERAL SOLER (451), LA AGUADA (452), LA BARRANQUITA (446), LA BRIANZA (453), LA GILDA (444), LAS GAMAS (454), LOS JOTES (455), PASO DE RIO SECO (456), PASO DEL DURAZNO (443), PUEYRREDON (457), PUNTA DEL AGUA (458), SAN AMBROSIO (459), SANTA RITA (460), TRES POZOS (461) |
| RÍO PRIMERO | 9 | CAÑADA HONDA (462), ESTACION MERCEDES (205), KILOMETRO 691 (465), MONTE DEL ROSARIO (464), NUEVA ANDALUCIA (466), PEDRO E. VIVAS (KM. 658) (195), POZO DE LA LOMA (467), RANGEL (468), TALA NORTE (EL ALCALDE) (463) |
| RÍO SEGUNDO | 1 | AGUA DE ORO (241), error del padrón |
| SAN ALBERTO | 3 | LAS MARAVILLAS (473), SAN HUBERTO (472), VILLA INTICO (474) |
| SAN JAVIER | 2 | EL CARRIZAL (475), QUEBRADA DE LOS POZOS (476) |
| SAN JUSTO | 14 | COLONIA 10 DE JULIO (477), COLONIA GENERAL DEHEZA (485), COLONIA LA COYUNDA (271), COLONIA LUIS A. SAUZE (479), COLONIA MALBERTINA (481), COLONIA SANTA MARIA (491), EL FUERTECITO (478), JERONIMO CORTES (482), LA CURVA (483), MONTE REDONDO (480), PLAYA GRANDE (490), PLAZA GENERAL DEHEZA (486), SAN ANTONIO (492), TRINCHERA (487) |
| SANTA MARÍA | 5 | COSME (496), JOSE DE LA QUINTANA (497), SIERRAS DE ORO (495), VILLA SAN NICOLAS (493), YOCSINA (494) |
| TERCERO ARRIBA | 1 | SALTO NORTE (500) |
| TOTORAL | 2 | EL TALITA (VILLA GUTIERREZ) (502), TOTORAL GRANDE (501) |
| TULUMBA | 1 | ROSARIO DEL SALADILLO (559) |
| UNIÓN | 2 | RAMON J. CARCANO (504), SAN SEVERO (505) |

## Propuesta de carga en el modelo de la spec (programa "Córdoba Hogar", `fuente = cordoba_hogar`)

| columna de la planilla | destino | cómo |
|---|---|---|
| DEPARTAMENTO, LOCALIDAD | `priv_plan_localidad.id_geo` | El `id_geo` del CSV. Las filas `revisar`/`sin_match` sin confirmar no se cargan y van al informe |
| Color de fila | `priv_plan_prioridades` → `prioridad_id` | Escala sembrada de la spec: celeste→1, verde→2, naranja→3, amarillo→4, rojo→5. **Gris → X (desestimado)**, igual que Villa Cerro Azul en CC: a confirmar. **Violeta → a definir con el área**. Hay dos opciones: crear una prioridad nueva en el catálogo de CH ("violeta", con su significado), o cargar el color de debajo (rojo/amarillo, columna `color_hab`). Hasta que se confirme, esas 7 filas se cargan sin prioridad |
| (no existe) | `priv_plan_estados` → `estado_id` | La planilla **no tiene columna de estado**. No hay valores que sembrar. El catálogo de estados de CH queda vacío hasta que el área lo defina |
| (no existe) | `ok_gobernador` | No hay columna. Queda NULL. Según §5.2, para las localidades que ya están en el panel de CH se muestra el `ok_gob` del panel |
| ANUNCIO DEL GOBERNADOR | Columna por defecto `anuncio_gobernador` (si_no) | `SI`→true (86), `NO`→false (340) |
| (no existe) | `monto_sugerido`, `monto_firmado` | Sin datos en la planilla. Quedan vacías |
| OBSERVACIÓN | Columna por defecto `observacion` (texto_largo) | Está vacía en todas las filas. No se carga nada |
| CANTIDAD DE VIVIENDAS | **Columna nueva** `cantidad_viviendas` (`numero`), nombre "Cantidad de viviendas" | Se crea la columna porque el área la tiene prevista, pero está vacía. No se carga ningún valor. Requiere la confirmación del usuario (spec §9.5) |
| TIPO | No se carga: calculada | `priv_localidades_info.tipo_localidad` (§5.1) |
| HAB | No se carga: calculada | `priv_localidades_info.habitantes` (§5.1) |
| VISITA DELGOBERNADOR | No se carga: calculada | Planilla de visitas, `ext_gob_visita_gobernador` (§5.1). `SI ANTERIOR` probablemente quiere decir "visitada en una gestión anterior", pero no se carga |
| CONVENIO DE VIVIENDA | No se carga: calculada | "¿Convenio de Vivienda?" sale de `convenio_firmado`/`fecha_firma_convenio` del panel de CH (§5.1). Conviene contrastar los 285 `SI` de la planilla contra el panel como control de la carga, pero solo como informe |
| REF EN EL GESTOR | No se carga: calculada | Se reemplaza por "¿Está en el panel?" (§5.1). Hay un solo valor (`3`, Los Molinos) |

**Preguntas para el usuario o el área**: (1) ¿Los colores de CH usan la misma escala 1–5 que CC? (2) ¿Qué significa el violeta? (3) ¿El gris es "desestimado"? (4) ¿Se crea igual la columna "Cantidad de viviendas", aunque esté vacía? (5) Confirmar las filas 121 (Paso del Durazno → 443, Río Cuarto) y 419 (Villa del Rosario del Saladillo → 559).
