from noticias.temas import (_compile, clasificar, es_espectaculos, es_fuente_multipais,
                            pais_por_contenido)

C = clasificar


def test_ana_no_colisiona_con_nombre_propio():
    # "ANA" (Autoridad Nacional del Agua) sola matcheaba el nombre "Ana".
    assert "Crop" not in C(
        "Sesión de la Comisión de Salud",
        "propuesto por la diputada Ana Luisa Yufra Lugo",
    )
    # La sigla completa (institucion real) sigue detectando Crop.
    assert "Crop" in C("Nota", "La Autoridad Nacional del Agua (ANA) otorgó licencias de riego")


def test_fiscal_solo_no_colisiona_con_carpeta_fiscal():
    # "fiscal" sola tambien es el sentido judicial ("carpeta fiscal").
    assert "KYC / AML / Financiero" not in C(
        "Sesión de la Comisión de Salud",
        "se denunció una carpeta fiscal con 140 folios de denuncias",
    )
    # El sentido tributario real sigue detectando la categoria.
    assert "KYC / AML / Financiero" in C("Nota", "el gobierno anunció una reforma del régimen tributario")


def test_plaguicidas_clasifica_como_crop():
    assert "Crop" in C(
        "El Estado sabía dónde fallaba el control de pesticidas. "
        "Ahora tiene plazos para corregirlo", None)
    assert "Crop" in C("TC declara fundada demanda sobre plaguicidas en zonas agrícolas", None)


def test_norma_de_interes():
    # Titulos reales (norma de datos biometricos de la SPDP).
    from noticias.temas import es_norma_de_interes as E
    assert E("Se expide la Norma General para el Tratamiento de Datos Biométricos")
    # Tramite que menciona el tema de pasada.
    assert not E("Autorizan viaje de profesionales de la Dirección General de "
                 "Medicamentos, Insumos y Drogas a Colombia")
    assert not E("Designan Director Ejecutivo de la Dirección de Productos Farmacéuticos")
    assert not E("Se aprueba el estatuto de la Iglesia Evangélica Bilingüe Unción Divina")
    assert not E(None)


def test_pais_por_contenido():
    # DPL News Ecuador (catalogada EC) traia esta nota peruana.
    assert pais_por_contenido(
        "Rafael Rey deja el Ministerio de Transportes y Comunicaciones de Perú",
        None, "EC") == "PE"
    assert pais_por_contenido(
        "Noboa llega a Estados Unidos para participar en la Asamblea General de la ONU",
        None, "PE") == "EC"
    # Sin ninguna señal de PE ni EC -> None.
    assert pais_por_contenido(
        "Cómo llegaría la economía de Milei a las elecciones de 2027, según analistas",
        None, "PE") is None
    assert pais_por_contenido("El chavismo y la oposición continúan el diálogo",
                               None, "EC") is None
    assert pais_por_contenido(None, None, "PE") == "PE", \
        "texto vacio: se queda con pais_fuente"
    assert pais_por_contenido(
        "Solana gana velocidad gracias a su nueva actualización",
        "La activación de SIMD-0525 redujo a 250 ms el tiempo de slot, el "
        "intervalo en que Solana produce nuevos bloques.", "EC") is None, \
        '"produce" (verbo) no debe matchear el Ministerio de la Produccion (PE), y sin otra señal es None'
    assert pais_por_contenido(
        "Nicaragua fortalece su preparación para la IA en salud",
        "el Ministerio de Salud de Nicaragua (MINSA) y la OPS...", "EC") == "EC", \
        "MINSA tambien es de Nicaragua - una sola sigla ambigua no alcanza si se nombra otro pais"
    assert pais_por_contenido(
        "Desmantelan 2 granjas clandestinas de minería de Bitcoin en Paraguay",
        "La Cámara de Diputados solicitó a la ANDE informes...", "EC") is None, \
        "sin señal real de PE/EC, nombrar a otro pais no alcanza para quedarse con pais_fuente"


def test_sin_senal_no_es_pais_fuente_aunque_nombre_otro_pais():
    assert es_fuente_multipais("Mundo Agropecuario")
    assert pais_por_contenido(
        "Argentina ajusta cultivos de verano al agua disponible",
        "Ensayos del INTA San Luis compararon maíz, sorgo, soja y maní "
        "para identificar estrategias capaces de estabilizar la "
        "producción en secano.", "EC") is None
    assert pais_por_contenido(
        "Del bosque a la colmena: así se obtiene la miel gallega",
        "Marcos Atrio y César trabajan entre robles y castaños para "
        "cosechar la miel oscura de Mel da Ziralla en un entorno rural "
        "de Galicia, España.", "EC") is None


def test_venezuela_no_es_ecuador():
    # "Asamblea Nacional" tambien es de Venezuela; "chavismo"/"TSJ" la delatan.
    assert es_fuente_multipais("Google News EC — Ley Orgánica")
    assert es_fuente_multipais("Google News PE — Decreto de Urgencia")
    assert not es_fuente_multipais("El Universo")
    assert pais_por_contenido(
        "Asamblea Nacional del régimen aprobó reforma parcial de Ley "
        "Orgánica del TSJ acordada en el diálogo entre el chavismo y la "
        "AN 2015 - NTN24", None, "EC") is None
    assert pais_por_contenido(
        "Asamblea Nacional aprueba por unanimidad reforma de la Ley "
        "Orgánica del TSJ - El Aragueño", None, "EC") is None
    assert pais_por_contenido(
        "Ley de Aviación Civil pasa a votación del pleno de la Asamblea "
        "Nacional", None, "EC") == "EC"


def test_tributo_no_es_homenaje():
    assert clasificar(
        "Black Sun une su heavy metal con la voz de Ñusta Picuasi en un "
        "tributo a 'La Pinta, la Niña'") == []
    assert clasificar(
        "Tributos que no aparecen: 7 de cada 10 empresas en Perú sienten "
        "que pagan a Sunat de más") == ["KYC / AML / Financiero"]


def test_es_espectaculos():
    # Farandula que menciona una enfermedad de pasada no es Salud.
    url_kardashian = "https://www.elcomercio.com/afull/kim-kardashian-esofagitis-salud-estados-unidos/"
    titulo_kardashian = ("Kim Kardashian recordó su hospitalización y encendió las "
                          "alarmas por antecedentes de cáncer en su familia")
    assert es_espectaculos(url_kardashian)
    assert clasificar(titulo_kardashian, None, url_kardashian) == []
    # El veto es por seccion del medio, no por palabra.
    assert clasificar(titulo_kardashian, None, None) == ["Salud"]
    assert clasificar(titulo_kardashian, None, "https://www.elcomercio.com/politica/nota") == ["Salud"]

    url_pelicula = ("https://eluniverso.com/entretenimiento/cine/pelicula-ecuatoriana-mama-"
                     "de-ana-cristina-benitez-gana-el-festival-internacional-de-cine-nota/")
    assert es_espectaculos(url_pelicula)
    assert clasificar(
        "Película ecuatoriana 'Mama' gana el Festival Internacional de Cine",
        "El documental presenta el diagnóstico de cáncer de mama en etapa avanzada de la directora.",
        url_pelicula,
    ) == []

    assert not es_espectaculos("https://www.gob.pe/institucion/minsa/noticias/1444776-nota")
    assert clasificar(
        "Minsa: La hinchazón o pesadez en el brazo tras el cáncer de mama requiere atención médica",
        None, "https://www.gob.pe/institucion/minsa/noticias/1444776-nota",
    ) == ["Salud"]


def test_ministro_no_es_proxy_de_tema():
    assert "Tech / Digital" not in clasificar(
        "Ministro Rogers Valencia visita terminal multipropósito de "
        "DP World en el Callao")
    assert clasificar(
        "Mincetur destaca nueva conexión aérea directa entre São Paulo y "
        "Cusco como impulso histórico para el turismo") == []


def test_presidente_de_club_no_es_coyuntura():
    assert clasificar("Miguel Montalvo, presidente de Barcelona SC, y el "
                       "cambio del club a sociedad anónima", None) == []
    assert "Coyuntura política" not in clasificar(
        "José David Jiménez, presidente de Emelec, plantea revisar el "
        "formato de Liga Ecuabet para recuperar a los hinchas en los estadios")
    assert clasificar("Presidenta Keiko Fujimori lidera sesión de "
                       "Consejo de Ministros en Palacio de Gobierno") == ["Coyuntura política"]


def test_medicinas_es_salud():
    assert clasificar("Compra de medicinas a la India se concretaría en las "
                       "próximas semanas") == ["Salud"]
    assert clasificar("Pacientes protestan por falta de fármacos oncológicos") == ["Salud"]
    # Singular fuera a proposito: la carrera no es tema Salud.
    assert clasificar("Estudiar Medicina: carrera de alta demanda, largo "
                       "camino y alto costo") == []


def test_plurales_y_keywords_eval():
    # Plurales y keywords del eval (clasificador/eval), con su contraejemplo.
    S, C_, T_, K = "Salud", "Crop", "Tech / Digital", "KYC / AML / Financiero"
    assert _compile(["digital"], plural=True).search("plataformas digitales")
    assert not _compile(["SIS"], plural=True).search("sises"), "siglas exactas"
    assert T_ in clasificar("Pagos digitales tendrán nuevas reglas desde 2027")
    assert C_ in clasificar("Negro amanecer para las agroexportaciones peruanas")
    # salud: solo en el titulo y no figurada
    assert S in clasificar("Campaña de salud gratis para este domingo 11 de octubre")
    assert S not in clasificar("Cinco claves para cuidar la salud financiera del hogar")
    assert S not in clasificar("Crédito suplementario contempla S/8 228 millones",
                               "financiar intervenciones en educación, salud, agua")
    assert S not in clasificar("Senasa capacitó a veterinarios para enfrentar la influenza aviar")
    # Crop: cultivos/ganado sustantivo, no "haber ganado"
    assert C_ in clasificar("Lluvias afectan 5.600 hectáreas de cultivos en Los Ríos")
    assert C_ in clasificar("Ganaderos de Ecuador, golpeados por caída de cabezas de ganado")
    assert C_ not in clasificar("Djokovic cae en Shanghái",
                                "Tres días después de haber ganado en Pekín el título 102")
    # Tech: redes sociales como objeto de regulacion, no "lo compartio en redes"
    assert T_ in clasificar("Marino Lavado plantea prohibir redes sociales a menores de 16 años")
    assert T_ not in clasificar("Gianella Marquina dio a luz",
                                "La hija compartió en sus redes sociales una fotografía")
    # KYC: pagos/finanzas, "bancos" (no banco de sangre)
    assert K in clasificar("BCRP prepara nuevas reglas para impulsar un ecosistema de pagos")
    assert K in clasificar("Bancos de América Latina multiplican sus ventas con IA")
    assert K not in clasificar("Hospital pide donantes: bancos de sangre en mínimos")


def test_vetos_eval():
    # Homonimos y tramites que marcaban un tema de cliente.
    S, C_, T_, K = "Salud", "Crop", "Tech / Digital", "KYC / AML / Financiero"
    # "Lavado" apellido vs lavado de activos
    assert K not in clasificar("Marino Lavado: “El peligro está ahí” ante posible "
                               "modificación de facultades en el Senado - Canal N")
    assert K in clasificar("Dos procesados reciben 10 años de cárcel por lavado")
    assert K in clasificar("Detienen a tres por Lavado de Activos en Guayaquil")
    # Nota del precio del dolar / Obras por Impuestos
    assert K not in clasificar("El dólar Sunat cotiza en S/ 3.442 para la venta este lunes")
    assert K not in clasificar("Adjudicaciones de Obras por Impuestos suman S/ 9409 millones")
    assert K in clasificar("Sunat fiscalizará impuestos a plataformas extranjeras")
    assert K not in clasificar("Aprueban transferencia financiera a favor de la Contraloría")
    assert K not in clasificar("Bancos comunitarios para el salvamento de las semillas nativas")
    assert K in clasificar("Primera entidad financiera 100% digital en Perú recibe luz verde")
    # INDECOPI ya no es Tech por si solo
    assert T_ not in clasificar("Indecopi multa con 455 UIT a empresa de tubulares")
    # Medio con "Digital" en el nombre (sufijo de Google News)
    assert T_ not in clasificar("Reunión de la COPROSA con el SENASA - Maraco Digital")
    assert T_ in clasificar("Gobierno lanza agenda digital 2030")
    # siembra figurada
    assert C_ not in clasificar("José Cabrera siembra incertidumbre sobre la fecha de las elecciones")
    assert C_ in clasificar("Inicia la siembra de arroz en Piura")
    # SeNaSa dominicano (seguro de salud) no es sanidad agraria
    assert C_ not in clasificar("Exfiscal enfrentará en libertad el juicio por el caso SeNaSa")
    assert C_ in clasificar("Senasa declara emergencia fitosanitaria por Fusarium R4T")
    # Tramite de norma (El Peruano / gob.pe) vs noticia de designacion
    assert clasificar("D000429-2026-MIDAGRI-DM — Se encarga a la señora MIRIAM BUSTAMANTE, "
                      "las funciones de Secretaria General") == []
    assert clasificar("DESARROLLO AGRARIO Y RIEGO — RESOLUCIÓN MINISTERIAL N° D000414-2026-"
                      "MIDAGRI-DM: Designan Jefa de Programación Multianual") == []
    assert C_ in clasificar("DESARROLLO AGRARIO Y RIEGO — DECRETO SUPREMO N° 012-2026-MIDAGRI: "
                            "Aprueban el Reglamento de plaguicidas de uso agrícola")
    assert S in clasificar("Designan a nuevo ministro de Salud tras renuncia")
    # Futbol: IESS/FEF no es Salud
    assert S not in clasificar("IESS le certificó a FEF que Santa Fe de Imbabura, en el "
                               "Ascenso Nacional, no afilió a los jugadores")
