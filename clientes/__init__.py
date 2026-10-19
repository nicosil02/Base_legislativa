"""Datos y configuracion de clientes. Al importarse abre los `*.cifrado`
que falten (ver clientes/privado.py), asi todo lo que lee clientes/ los
encuentra en texto: la web, los workflows y los tests."""
try:
    from clientes.privado import abrir as _abrir
    _abrir()
except Exception as _e:  # clave equivocada o archivo roto: que se vea, sin tumbar la app
    print(f"[clientes] no pude abrir los datos cifrados: {_e}")
