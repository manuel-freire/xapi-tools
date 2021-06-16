#!/usr/bin/python3

import json, re
import argparse

from datetime import datetime

import copy
import numpy as np

import sys

def main(input_files, output_file, mappings_file, not_before, not_after, index, filter, limit_actors, verbosity):

    # build translator
    with open(mappings_file, 'r') as mappings_f:
        translator = Translator(json.load(mappings_f), verbosity)

    # process each file, filtering while doing so
    output = []
    actors = {}
    current = 0
    for input_file in input_files:
        with open(input_file, 'r') as input_f:
            data = json.load(input_f)            
            hits = data["hits"]["hits"]

            input_counter = 0
            output_counter = 0
            discarded_by_filter = 0
            discarded_by_actor_limit = 0   
            discarded_by_date_filter = 0         
                    
            print(f'processing {len(hits)} traces from {input_file}...')
            
            for h in hits:
                input_counter = input_counter+1
                source = h["_source"]
                actor_name = source["name"]
                timestamp = source["timestamp"]
                if not_before is not None and timestamp < not_before:
                    discarded_by_date_filter = discarded_by_date_filter+1
                    continue
                if not_after is not None and timestamp > not_after:
                    discarded_by_date_filter = discarded_by_date_filter+1
                    continue
                if filter is not None and not re.match(filter, actor_name):
                    discarded_by_filter = discarded_by_filter+1
                    continue
                if limit_actors is not None:
                    if actor_name not in actors:
                        if len(actors) >= limit_actors:
                            discarded_by_actor_limit = discarded_by_actor_limit+1
                            continue
                        else:
                            actor = {"low": timestamp, "high": timestamp, "statements": 0}
                            actors[actor_name] = actor
                    else:
                        actor = actors[actor_name]
                if index is not None and index != current:
                    continue

                output_counter = output_counter+1
                result = translator.translate(source)
                actor["low"] = min(actor["low"], timestamp)
                actor["high"] = max(actor["low"], timestamp)
                actor["statements"] = actor["statements"]+1
                output.append(result)
                
            print(f'generated {output_counter} output xAPI-SG statements from {input_counter} input traces in {input_file}:'
                f'\n\t {discarded_by_date_filter} discarded by date filter'
                f'\n\t {discarded_by_filter} discarded by actor name filter'
                f'\n\t {discarded_by_actor_limit} discarded by actor limit')

    # output actors
    for name, info in actors.items():
        low, high = info["low"], info["high"]
        lowt = datetime.fromisoformat(re.sub("Z","",low))
        hight = datetime.fromisoformat(re.sub("Z","",high))
        print(f'{name}: {lowt} to {hight}, {hight-lowt}, {info["statements"]} statements')

    # run through t-mon for sanity
    timeformats=['%Y-%m-%dT%H:%M:%SZ','%Y-%m-%dT%H:%M:%S.%fZ'] #array of time format
    players_info = {}
    for s in output:
        process_xapisg_statement(s, players_info, timeformats)

    for name, info in players_info.items():
        print(f'{name}{json.dumps(info, indent=2, default=str)}')

    # output output
    with open(output_file, 'w') as output_f:
        json.dump(output, output_f, sort_keys=False, indent=2)

template_player_info = {
    "game_started": False, "game_completed": False,
    "interactions":{}, #dict of interactions
    "game_progress_per_time": [], # list of pairs (game progress, timestamp)
    "completables_scores": {}, # dict completable : last score
    "completables_progress": {}, # list of pairs completable : last progress
    "completables_times": {}, # dict completable: (start, end)
    "alternatives": {}, # dict alternative: list of pairs (response, correct (T/F))
    "action_type_interaction":{}, #dict of action type interactions
    "accessible":{}, #dict of accessible
    "videos_seen": [], # list of videos seen (accessed) by player
    "videos_skipped": [], # list of videos skipped by player
    "selected_menus":{} #dict of menus and response selected
}

def timestampTotimedate(timestamp, timeformats):
    t=None
    for timeformat in timeformats:
        try:
           t = datetime.strptime(timestamp, timeformat)
        except ValueError:
            pass
    if t==None:
        str="TimeFormatError : This timestamp don't match with formats in "
        for format in timeformats:
            str+=format+" "
        raise TimeFormatError(timestamp, str)
    else:
        return t

def process_xapisg_statement(data, players_info, timeformats):
    # available keys in statement
    keys = data.keys()

    ## extracting fields from xAPI-SG statement
    # actor field
    if "actor" in keys:
        if "name" in data["actor"].keys():
            actor_name = data["actor"]["name"]

            if actor_name not in players_info.keys():
                players_info[actor_name] = copy.deepcopy(template_player_info)

            player_info = players_info[actor_name]

    # verb field
    if "verb" in keys:
        if "id" in data["verb"].keys():
            verb_id = data["verb"]["id"]
            # process verb field
            verb_xapi = np.array(verb_id.split("/"))[-1]

    # object field
    if "object" in keys:
        if "id" in data["object"].keys():
            object_id = data["object"]["id"]
            # process object id field
            object_id_name = np.array(object_id.split("/"))[-1]
        if "definition" in data["object"].keys() and "type" in data["object"]["definition"].keys():
            object_type = data["object"]["definition"]["type"]
            # process object type field
            object_type_xapi = np.array(object_type.split("/"))[-1]
    action_type=None
    # result field
    if "result" in keys:
        if "extensions" in data["result"].keys():
            if "response" in data["result"].keys():
                result_response = data["result"]["response"]
            res = data["result"]["extensions"]
        else:
            res = data["result"]
        if "success" in res.keys():
            result_success = res["success"]
        if "response" in res.keys():
            result_response = res["response"]
        if "progress" in res.keys():
            result_progress = res["progress"]
        elif "https://w3id.org/xapi/seriousgames/extensions/progress" in res.keys():
            result_progress = res["https://w3id.org/xapi/seriousgames/extensions/progress"]
        if "score" in res.keys():
            result_score = res["score"]
        if "action_type" in res.keys():
            action_type=res["action_type"]

    # timestamp field
    if "timestamp" in keys:
        timestamp = data["timestamp"]

    ## update values
    try:
        # initialized traces
        if verb_xapi.lower()=="initialized":
            if object_type_xapi.lower()=="serious-game":
                player_info["game_started"] = True
                if timestamp:
                    try:
                        t=timestampTotimedate(timestamp, timeformats)
                        player_info["game_progress_per_time"].append([0,t])
                    except TimeFormatError as e :
                        print(e)
            if timestamp:
                try:
                    t=timestampTotimedate(timestamp, timeformats)
                    player_info["completables_times"][object_id_name] = t
                except TimeFormatError as e :
                    print(e)
        # completed traces
        elif verb_xapi.lower()=="completed":
            if object_type_xapi.lower()=="serious-game":
                player_info["game_completed"] = True
                if timestamp:
                    try:
                        t=timestampTotimedate(timestamp, timeformats)
                        player_info["game_progress_per_time"].append([1,t])
                    except TimeFormatError as e :
                        print(e)
            if timestamp and object_id_name in player_info["completables_times"].keys():
                try:
                    t=timestampTotimedate(timestamp, timeformats)
                    player_info["completables_times"][object_id_name] = \
                                                    (player_info["completables_times"][object_id_name], t)
                except TimeFormatError as e :
                    print(e)
            if object_id_name and timestamp and result_score:
                player_info["completables_scores"][object_id_name]=result_score
        # progressed traces
        elif verb_xapi.lower()=="progressed":
            if object_type_xapi.lower()=="serious-game" and timestamp and result_progress:
                try:
                    t=timestampTotimedate(timestamp, timeformats)
                    player_info["game_progress_per_time"].append([result_progress,t])
                    if result_progress==1:
                        player_info['game_completed'] = True
                except TimeFormatError as e :
                    print(e)
            if verb_xapi.lower()=="progressed" and object_id_name and result_progress:
                try:
                    t=timestampTotimedate(timestamp, timeformats)
                    print(" \t-- any-advance: ", t)
                    if not object_id_name in player_info["completables_progress"].keys():
                        player_info["completables_progress"][object_id_name]=[]
                    player_info["completables_progress"][object_id_name].append([result_progress,t])
                except TimeFormatError as e :
                    print(e)
        # interacted traces
        elif verb_xapi.lower()=="interacted":
            if timestamp:
                try:
                    t = timestampTotimedate(timestamp, timeformats)
                except TimeFormatError as e:
                    print(e)
            if action_type!=None:
                if not object_type_xapi in player_info["action_type_interaction"].keys():
                    player_info["action_type_interaction"][object_type_xapi]={}
                if not object_id_name in player_info["action_type_interaction"][object_type_xapi].keys():
                    player_info["action_type_interaction"][object_type_xapi][object_id_name]={}
                if not action_type in player_info["action_type_interaction"][object_type_xapi][object_id_name].keys():
                    player_info["action_type_interaction"][object_type_xapi][object_id_name][action_type]=[]
                player_info["action_type_interaction"][object_type_xapi][object_id_name][action_type].append(t)
            else:
                if not object_type_xapi in player_info["interactions"].keys():
                    player_info["interactions"][object_type_xapi]={}
                if not object_id_name in player_info["interactions"][object_type_xapi].keys():
                    player_info["interactions"][object_type_xapi][object_id_name]=[]
                player_info["interactions"][object_type_xapi][object_id_name].append(t)
        # selected traces
        elif verb_xapi.lower()=="selected":
            if object_type_xapi.lower()=="alternative":
                if object_id_name and result_response and result_success != None:
                    if object_id_name in player_info["alternatives"].keys():
                        player_info["alternatives"][object_id_name].append((result_response, result_success))
                    else:
                        player_info["alternatives"][object_id_name] = [(result_response, result_success)]
            elif object_type_xapi.lower()=="menu":
                if result_response:
                    if not object_id_name in player_info["selected_menus"].keys():
                        player_info["selected_menus"][object_id_name]={}
                    if not result_response in player_info["selected_menus"][object_id_name].keys():
                        player_info["selected_menus"][object_id_name][result_response]=[]
                    if timestamp:
                        t=timestampTotimedate(timestamp, timeformats)
                        player_info["selected_menus"][object_id_name][result_response].append(t)
        # accessed traces
        elif verb_xapi.lower()=="accessed":
            if object_type_xapi.lower()=="cutscene" and object_id_name:
                player_info["videos_seen"].append(object_id_name)
            elif object_type_xapi.lower()=="accessible" and object_id_name:
                if not object_id_name in player_info["accessible"].keys():
                    player_info["accessible"][object_id_name]=[]
                t=timestampTotimedate(timestamp, timeformats)
                player_info["accessible"][object_id_name].append(t)
        # skipped traces
        elif verb_xapi.lower()=="skipped":
            if object_type_xapi.lower()=="cutscene" and object_id_name:
                player_info["videos_skipped"].append(object_id_name)
    except NameError:
        pass#%% md

class Translator:
    """Translates one JSON to another using a mapping"""

    # regular expression used to add substitutions to mapping file
    subst_regex = re.compile(r"""
            [$]\{       # match ${ to start escape
            ([^)}]+)      # group 1:anything before end, or 1st parens start
            (\((.*)\))?   # (group 3: optional args within parens )
            \}          # end the escape
        """, re.VERBOSE)

    def __init__(self, mappings, verbosity):
        """ mappings describes what output to generate for different inpu types
            verbosity >0 will result in diagnostic messages for each trace
            verbosity >1 will show even more details
        """
        self.mappings = mappings
        self.verbosity = verbosity

    def translate(self, input):

        if (self.verbosity > 0):
            print("|| -- input --> ", 
                json.dumps(input, sort_keys=False, indent=2))

        mapping = None
        for m in self.mappings:
            if m["name"] == input["event"]: 
                mapping = m
                break
        if mapping == None: raise "No mapping found for " + m["name"]

        if (self.verbosity > 0):
            print("chosen mapping is: ", 
                json.dumps(mapping["output"], sort_keys=False, indent=2))
        
        output = self.apply_template(mapping["output"], input)

        if (self.verbosity > 0):
            print("|| -- output --> ",
                json.dumps(output, sort_keys=False, indent=2))
        return output

    def subst_in_str(self, key, args, event):
        if args is None:
            return event[key]
        elif key == "initialized.id":
            type = event["type"]
            if type == "serious-game": return args
            else: return args + type
        else:
            raise "Unknown subst"

    def apply_template(self, o, event):
        
        if (self.verbosity > 1):
            print("recursing into: ", json.dumps(o, sort_keys=False, indent=2))
       
        result = None
        if isinstance(o, str):
            m = Translator.subst_regex.match(o)
            if m is not None:
                result = event[m.group(1)] # a full match may yield int
            else:                        # partial matches may not
                result = re.sub(Translator.subst_regex, 
                    lambda m: self.subst_in_str(m.group(1), m.group(3), event), o)
        elif isinstance(o, object):
            output = {}
            for k, v in o.items():
                mk = Translator.subst_regex.match(k)
                if mk is not None:
                    # builds name of method to call: ${whatever} => self.proc_whatever
                    processor = getattr(self,  "proc_" + mk.group(1))
                    processor(mk.group(3), event, output)
                else:
                    output[k] = self.apply_template(v, event)
            result = output
        else:
            result = o

        if (self.verbosity > 1):
            print("result is: ", result)     
        return result              

    def proc_type(self, args, event, output):
        prefix, ev_key = args.split(',')
        output["type"] = prefix + event[ev_key].title()

    def proc_variables(self, args, event, output):
        
        results = {}
        extensions = {}
        results["extensions"] = extensions
        if "result" in output:
            results = output["result"]
            if "extensions" in results:
                extensions = results["extensions"]

        ignored = {'name', 'timestamp', 'event', 'target', 'type', 'progress'}
        for k, v in event.items():
            if not k in ignored:
                extensions[args + k] = v
        
        if len(extensions) > 0:
            output["result"] = results

    def proc_optional(self, args, event, output):
        if args in event:
            output[args] = event[args]        

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=\
        "Reformat RAGE traces back to the xAPI-SG from whence they came")
    parser.add_argument("input_files", nargs='+',
            help="One or more files with RAGE's Elastic-Search traces")
    parser.add_argument("--output_file", 
            help="A file with xAPI-SG formatted traces")
    parser.add_argument("--mappings_file", 
            help="A file with mappings from one to the other")
    parser.add_argument("--index", type=int,
            help="Index of input to use")  
    parser.add_argument("--filter",
            help="Regular expression that actor names must match to be included")
    parser.add_argument("--limit_actors", type=int,
            help="After building traces with this many different actors, ignore incoming from additional actors")
    parser.add_argument('-v', '--verbose', 
            help="Verbosity. Use more '-v's, max 3, to print more diagnostic messages to the console",
            action='count', default=0)
    parser.add_argument("--not_before",
            help="Reject traces with a timestamp lower than this one")              
    parser.add_argument("--not_after",
            help="Reject traces with a timestamp lower than this one")              
    args = parser.parse_args()

    main(args.input_files, args.output_file, args.mappings_file, 
        args.not_before, args.not_after,
        args.index, args.filter, args.limit_actors, args.verbose)
    