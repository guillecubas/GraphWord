# Validación de esta etapa

Entorno local: Python 3.12.13.

Comando ejecutado: `python -m unittest discover -s tests -v`.
Resultado: 12 tests, 0 errores y 0 fallos.

Incluye 80 combinaciones de diccionario y número de particiones dentro de la prueba
de equivalencia (20 entradas generadas con semilla fija × 4 configuraciones). El
oráculo compara pares de palabras y no reutiliza el algoritmo por patrones.

Se comprobaron también duplicados, palabras aisladas, distintas longitudes,
normalización, camino mínimo, ausencia de camino, nodos desconocidos, grado,
componentes, entradas vacías, índices inválidos y estabilidad entre dos intérpretes
con distinta semilla de hash. La CLI se ejecuta en un subproceso durante las pruebas.

Demostración ejecutada:

```bash
python -m graphword data/words3.txt --partitions 4 --from cat --to dad
```

Resultado: 20 nodos, 29 aristas, 2 componentes; grado máximo 6 (`bat`);
camino `cat → bat → bad → dad`; ejecución `local-sequential`.

No verificado: ejecución en Python 3.11, construcción Docker, CI remoto,
API HTTP, comportamiento distribuido, despliegue AWS o rendimiento bajo carga.
El workflow está preparado para Python 3.11 y 3.12, pero configurarlo no prueba
que haya sido ejecutado en GitHub.
