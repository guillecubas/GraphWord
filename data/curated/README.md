# Diccionarios trazables de GraphWord

Se cruzan dos fuentes diferentes: el diccionario estadounidense Hunspell derivado
de SCOWL que distribuye LibreOffice y el diccionario de pronunciación CMUdict.
Las revisiones completas, URLs y SHA-256 están en [manifest.json](manifest.json).
No se usa una descarga cambiante de `main` o `master` al regenerarlos.

## Qué se hace y por qué

1. SCOWL/Hunspell: leer las formas base del fichero `.dic`, quitar indicadores de
   afijos y excluir la marca `NOSUGGEST` declarada en `.aff`. No se expanden afijos.
2. Admitir únicamente entradas que ya son minúsculas ASCII y tienen 3–8 letras.
   Esto elimina nombres capitalizados, guiones y apóstrofos; no elimina todos los
   nombres propios que alguna fuente haya escrito en minúsculas.
3. CMUdict: unificar variantes de pronunciación, exigir fonemas del inventario
   oficial y al menos una vocal con marca de acento. Admitir entradas en minúsculas.
4. Conservar la intersección, ordenar y eliminar duplicados. La presencia en la
   fuente léxica es nuestro criterio operativo de palabra significativa; una
   pronunciación registrada es nuestro criterio de pronunciabilidad.
5. Separar por longitud y guardar las dos listas intermedias, las licencias y las
   huellas de entradas y resultados para poder auditar la transformación.

Es un filtro documentado, no una prueba lingüística perfecta: puede haber errores,
acrónimos o vocabulario raro. No infiere significados ni genera pronunciaciones.
Al no expandir afijos, no representa todas las formas flexionadas del inglés.
Los archivos históricos de `data/` fuera de esta carpeta no forman parte de este
corpus: no atribuimos a esas listas una procedencia que no se ha comprobado.

| Letras | Palabras de la intersección |
|---|---:|
| 3 | 628 |
| 4 | 1889 |
| 5 | 2677 |
| 6 | 3676 |
| 7 | 3898 |
| 8 | 3723 |

Antes de intersectar: 22070 formas base léxicas y 84373 entradas pronunciadas
válidas según estos filtros. Intersección total: 16491 palabras.

## Reproducción y licencias

Desde la raíz del repositorio: `python scripts/build_corpus.py`. Requiere Internet;
las pruebas y los benchmarks usan las copias versionadas, sin descargar nada.
El script regenera los archivos de esta carpeta; comparar el manifiesto con Git
permite detectar cambios inesperados.

- [Avisos íntegros de SCOWL y sus fuentes](licenses/scowl-README_en_US.txt): se
  conservan todos, no se sustituye la licencia colectiva por una licencia propia.
- [Licencia de CMUdict](licenses/cmu-LICENSE): mantener el aviso de copyright y las
  condiciones al redistribuir. Los datos derivados conservan estos avisos.
- Fuentes originales: [LibreOffice dictionaries](https://github.com/LibreOffice/dictionaries/tree/32b006a2c22a4ac7e8ed3f03346f7b3d85a970a4/en)
  y [CMUdict](https://github.com/cmusphinx/cmudict/tree/74790861f652b15e4ac49015a90074ad62a27690).

El ZIP desplegado incluye `words3.txt` a `words8.txt`, el manifiesto y los avisos.
Las listas intermedias se conservan en Git, no son necesarias en los workers.
