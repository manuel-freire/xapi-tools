# RAGE-to-xAPI trace translator

El programa `translator.py` coge un fichero de salida de RAGE-Analytics/ElasticSearch, y lo convierte a xAPI. 

Para ello,
* para cada traza del fichero de entrada
* busca un patrón en mapping.json
* y aplica el patrón a la traza

Por tanto, genera exactamente 1 traza de salida por cada traza de entrada.

Parámetros (según la ayuda)

~~~{.txt}
usage: translator.py [-h] [--output_file OUTPUT_FILE] [--mappings_file MAPPINGS_FILE] [--index INDEX] [--filter FILTER] [--limit_actors LIMIT_ACTORS] [-v] [--not_before NOT_BEFORE] [--not_after NOT_AFTER]
                     input_files [input_files ...]

Reformat RAGE traces back to the xAPI-SG from whence they came

positional arguments:
  input_files           One or more files with RAGE's Elastic-Search traces

optional arguments:
  -h, --help            show this help message and exit
  --output_file OUTPUT_FILE
                        A file with xAPI-SG formatted traces
  --mappings_file MAPPINGS_FILE
                        A file with mappings from one to the other
  --index INDEX         Index of input to use
  --filter FILTER       Regular expression that actor names must match to be included
  --limit_actors LIMIT_ACTORS
                        After building traces with this many different actors, ignore incoming from additional actors
  -v, --verbose         Verbosity. Use more '-v's, max 3, to print more diagnostic messages to the console
  --not_before NOT_BEFORE
                        Reject traces with a timestamp lower than this one
  --not_after NOT_AFTER
                        Reject traces with a timestamp lower than this one
~~~

Ejemplo de uso:

~~~
./translator.py traces1.json traces2.json --output_file t2.json --mappings_file mapping.json --filter "^[A-Z]{4}$" --limit_actors 24 --not_before 2017-01-30 --not_after 2017-01-31
~~~

Donde, si se especifica `--index algo`, sólo se procesará la traza número `algo` (útil para depurar).

Y si se especifican filtros, se pueden excluir ciertas trazas.

## mappings.json

Contiene un array de tipos de traza. Para cada tipo, contiene un `name` (que debe corresponder con el tipo de evento), un `output` (el patrón de salida), y ejemplos de entrada (para inspirarse cuando escribes el patrón de salida).

El `output` puede contener:
* json estándar, que se preserva en la salida
* expresiones que corresponden exactamente a `${algo}` en el *valor*, en cuyo caso el valor es reemplazado por el valor de `evento.algo`. *Esto preserva los tipos de números y booleanos*.
* expresiones que contienen (pero no exclusivamente) un `${algo}` en el *valor*, en cuyo caso cada ocurrencia es reemplazada por el valor de `evento.algo`, preservando el resto de la cadena.
* expresiones de la forma `${algo(argumentos)}` en la *clave*. En este caso, se invoca un procesador especial en el código -- y se ignora el *valor*. Ahora mismo hay definidos los siguientes procesadores especiales:

~~~{python}

    # "${type(https://rage.e-ucm.es/xapi/seriousgames/activities/,type)}" => 
    #    "type": "https://rage.e-ucm.es/xapi/seriousgames/activities/Cutscene"
    #    (asumiendo event.type == "cutscene")
    def proc_type(self, args, event, output):
        prefix, ev_key = args.split(',')
        output["type"] = prefix + event[ev_key].title()

    # "${variables(https://first-aid-game.e-ucm.es/variables/)}": null,
    #    para cada clave NO en {'name', 'timestamp', 'event', 'target', 'type', progress'}
    #    genera, en results.extensions, una línea de la forma 
    #        "https://first-aid-game.e-ucm.es/variables/clave": "valor"
    #    (donde el valor se busca en el evento original)
    def proc_variables(self, args, event, output):        
        results = {}
        extensions = {}
        results["extensions"] = extensions
        if "result" in output:
            results = output["result"]
            if "extensions" in results:
                extensions = results["extensions"]

        ignored = {'name', 'timestamp', 'event', 'target', 'type', 'progress', 'time'}
        for k, v in event.items():
            if not k in ignored:
                extensions[args + k] = v
        
        if len(extensions) > 0:
            output["result"] = results

    # "${optional(success)}": "${success}"
    #    si event.success==true, genera "success": true (o lo que valga)
    #    si no existe event.success, no genera nada
    def proc_optional(self, args, event, output):
        if args in event:
            output[args] = event[args]    
~~~

Para definir nuevos procesadores, usa `proc_nombre` como nombre, los mismos argumentos que tienen los demás, y usa `${nombre(args)}` en una **clave** de tu mapping.json


