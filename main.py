from flask import Flask, render_template, request, jsonify, redirect, session, url_for

import sqlite3
import logging
import re
import random


app = Flask(__name__, static_url_path='/static')
app.config['SECRET_KEY'] = b'\xae3\xc1\xef>Q?\x81\xff\x07\xb9)'
DB_PATH = "SPEED_SHADOWING.db"

@app.route('/', methods=["GET"])
def home():

    active_events = get_events()
    print("ACTIVE: ", active_events)

    return render_template(
                "index.html",
                active_events=active_events,
            )

@app.route('/events/<eventID>', methods=["GET","POST"])
def load_session(eventID):
    
    event_name, location, open_to, _, host, start_date, end_date = get_event_details(eventID)
    print(event_name, location, open_to, host, start_date, end_date)
    count = get_signup_count(eventID)

    details = {k:v for k,v in request.args.items()} if request.args else {}
    print(details)

    errors = session.get("errors")
    if errors:
        del session["errors"]
    
    return render_template(
                "shadow_session.html",
                errors=errors,
                eventID=eventID,
                event_name=event_name,
                location=location,
                open_to=open_to,
                host=host,
                start_date=start_date,
                end_date=end_date,
                signup_count=count,
                details=details,
            )

@app.route('/events/<eventID>/participants', methods=["GET","POST"])
def view_participants(eventID):
    
    # TODO: validate admin/host user
    
    event_name, location, open_to, _, host, start_date, end_date = get_event_details(eventID)
    print(event_name, location, open_to, host, start_date, end_date)

    participants = get_signed_up(eventID)
    if participants:
        participants = [list(x) for x in participants]
        for person in participants:
            skills = get_skill_string(person[8])
            interests = get_skill_string(person[9])
            person[8], person[9] = skills, interests


    signup_count = len(participants)
    
    return render_template(
                "view_participants.html",
                participants=participants,
                signup_count=signup_count,
                eventID=eventID,
                event_name=event_name,
                location=location,
                open_to=open_to,
                host=host,
                start_date=start_date,
                end_date=end_date,
            )


@app.route('/submit/<eventID>', methods=["POST"])
def submit(eventID):

    sid, name, email, location, title, lob, team, skills, interests = get_user_inputs(request.form)

    valid, message = validate_register(eventID, sid, email, location, skills, interests)
    if not valid:
        print(message)
        session['errors'] = message
        return redirect(url_for(
                                'load_session',
                                eventID=eventID,
                                sid=sid,
                                name=name,
                                email=email,
                                location=location,
                                title=title,
                                lob=lob,
                                team=team,
                                skills=skills,
                                interests=interests,
                            )
                        )

    register(sid, eventID, name, email, location, title, lob, team, skills, interests)
    
    return redirect("/events/" + eventID)

@app.route("/search_query", methods=["GET"])
def search_query() -> dict:

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        chars = request.args.get("chars")

        pattern1 = f"{chars}%"
        pattern2 = f"%{chars}%"

        cur.execute(
            "WITH T1 AS ("
            "SELECT INTEREST_ID, NAME "
            "FROM ALL_INTERESTS "
            "WHERE NAME LIKE ? "
            ") "
            "SELECT * FROM ( "
            "SELECT '1' AS PRIORITY, T1.* FROM T1 "
            "UNION "
            "SELECT '2' AS PRIORITY, INTEREST_ID, NAME "
            "FROM ALL_INTERESTS "
            "WHERE NAME LIKE ? "
            "AND NAME NOT IN (SELECT NAME FROM T1) "
            ") "
            "ORDER BY PRIORITY, NAME;",
            (pattern1,
             pattern2,),
        )

        interests = cur.fetchall()

    return jsonify(interests)

@app.route("/events/<eventID>/close", methods=["GET"])
def close_applications(eventID):
    pass

@app.route("/events/<eventID>/remove/<SID>", methods=["POST"])
def remove_from_event(eventID, SID):
    logging.warning(f"Removing {SID} from event {eventID}")
    
    remove_participant(eventID, SID)

    return redirect(f"/events/{eventID}/participants")

#TODO: Send email to all participants in one click
@app.route("/events/<eventID>/match/email", methods=["GET"])
def email_matches(eventID):#matches, triple, eventID):

    event_name, location, open_to, _, host, start_date, end_date = get_event_details(eventID)
    
    print(request.args)

    return redirect(f"/events/{eventID}/match")

    #TODO: email template


@app.route("/events/<eventID>/match", methods=["GET"])
def match_participants(eventID):

    found = False

    event_name, location, open_to, _, host, start_date, end_date = get_event_details(eventID)
    print(event_name, location, open_to, host, start_date, end_date)

    participants = get_signed_up(eventID)
    signup_count = len(participants)

    data = get_existing_matches(eventID)
    if data:
        saved_participants, saved_matches = data

        saved_participants_set = set(saved_participants.split(','))
        existing_participants_set = set([x[0] for x in participants])

        if saved_participants_set == existing_participants_set:
            compatability, saved_triple = expand_saved_matches(saved_matches)
            triple = populate_matches_for_display(saved_triple, eventID) if saved_triple else None
            matches = [populate_matches_for_display(x, eventID) for x in compatability]
            found = True
            logging.warning("~~Populating saved~~")

    
    if not found:
        compatability, missing = populate_compatibility(participants)
        
        if missing:
            print(f"missing: {missing}")
            group = find_group(compatability, missing, eventID)
            total_compat = (compatability[group[0]][0] + group[2]) * (2/3)
            del compatability[group[0]]
            compatability.sort(key=lambda item: item[0], reverse=True)

            triple = (round(total_compat,3), group[1][0], group[1][1], missing)
            triple = populate_matches_for_display(triple, eventID)
        else:
            triple = None
        
        print("||--->", compatability)

        matches = [populate_matches_for_display(x, eventID) for x in compatability]

        save_matches(eventID, participants, matches, triple)

        logging.warning("~~Populating new~~")

    logging.warning(matches)
    logging.warning(triple)

    return render_template(
                "view_matches.html",
                matches=matches,
                triple=triple,
                signup_count=signup_count,
                eventID=eventID,
                event_name=event_name,
                open_to=open_to,
                host=host,
                start_date=start_date,
                end_date=end_date,
            )

#TODO: Browse colleagues by knowledge
@app.route("/knowledge/browse", methods=["GET", "POST"])
def browse_knowledge():

    details = {k:v for k,v in request.args.items()} if request.args else {}
    print(details)

    return render_template(
                "browse_knowledge.html",
            )

#TODO: Register for shadowing
@app.route("/knowledge/register", methods=["GET", "POST"])
def register_knowledge():

    details = {k:v for k,v in request.args.items()} if request.args else {}
    print(details)

    return render_template(
                "self_register.html",
                details=details,
            )

@app.route("/events/<eventID>/mock", methods=["GET"])
def mock_person(eventID):

    letters = 'VWFSIE'
    numbers = '0123456789'
    names = ['Jeff', 'Steve', 'John', 'Clive', 'Jamie', 'Bob', 'Daniel', 'Ed', 'Harry', 'Louise', 'Jessica', 'Emily', 'Laura']
    locations = ['Bournemouth', 'London', 'Glasgow', 'Dublin', 'Israel']
    titles = ['MD', 'ED', 'VP', 'Associate', 'Analyst', 'Apprentice']
    lobs = ['CIB', 'GTI', 'AWM', 'Athena', 'PTT']
    #teams = ['SFTR Reg Reporting', 'Athena Python', 'GAIA cloud', 'Airflow', 'UITK', 'Onyx']

    valid = False
    while not valid:
        sid = random.choice(letters) + ''.join([random.choice(numbers) for _ in range(5)])
        names = random.sample(names, random.randint(1,3))
        name = ' '.join(names)
        email = f"{'.'.join(names)}@jpmorgan.com"
        location = random.choice(locations)
        title = random.choice(titles)
        lob = random.choice(lobs)
        team = 'MockTeam' #random.choice(teams)

        valid = validate_register(eventID, sid, email, location, ['x'], ['x'])[0]

    skill_ids = random.sample(range(1,101), random.randint(1,12))
    interest_ids = random.sample(range(1,101), random.randint(1,12))

    print(sid, eventID, name, email, location, title, lob, team)
    print(skill_ids, interest_ids)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        s, i = [], []
        for s_id in skill_ids:
            cur.execute(
                "SELECT INTEREST_ID, NAME "
                "FROM ALL_INTERESTS "
                "WHERE INTEREST_ID = ?;",
                (s_id,)
            )
            s.append('//'.join([str(x) for x in cur.fetchone()]))
        for i_id in interest_ids:
            cur.execute(
                "SELECT INTEREST_ID, NAME "
                "FROM ALL_INTERESTS "
                "WHERE INTEREST_ID = ?;",
                (i_id,)
            )
            i.append('//'.join([str(x) for x in cur.fetchone()]))
    skills = '|'.join(s)
    interests = '|'.join(i)

    register(sid, eventID, name, email, location, title, lob, team, skills, interests)

    return redirect(f"/events/{eventID}/participants")


def expand_saved_matches(matches):

    matches_list = [x.split(",") for x in matches.split("|")]

    expanded_matches = []
    extra = None
    for m in matches_list:
        if len(m) == 3:
            expanded_matches.append(m)
        elif len(m) == 4:
            extra = m
        else:
            logging.warning(f"{m} - Length = {len(m)}")

    return expanded_matches, extra


def get_existing_matches(eventID):

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT PARTICIPANTS, MATCHES "
            "FROM FOUND_MATCHES "
            "WHERE EVENT_ID = ? "
            "AND GENERATE_TS = "
            "(SELECT MAX(GENERATE_TS) FROM FOUND_MATCHES WHERE EVENT_ID=?);",
            (eventID,eventID)
        )
        res = cur.fetchone()    
    if res:
        return res[0], res[1]
    else:
        return None

    
def save_matches(eventID, participants, matches, triple):

    _participants = ','.join([x[0] for x in participants])

    _matches = [(str(x[0]), x[1][0], x[2][0]) for x in matches]
    if triple:
        _triple = f"|{triple[0]},{triple[1][0]},{triple[2][0]},{triple[3][0]}"
    else:
        _triple = ''
    
    _matches = "|".join([",".join(x) for x in _matches]) + _triple

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO FOUND_MATCHES "
            "(EVENT_ID, PARTICIPANTS, MATCHES, GENERATE_TS) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP);",
            (eventID, _participants, _matches)
        )
        conn.commit()
    

def populate_matches_for_display(pair, eventID):

    if len(pair) == 4:
        p1 = list(get_user_from_sid(eventID,pair[1]))
        p2 = list(get_user_from_sid(eventID,pair[2]))
        p3 = list(get_user_from_sid(eventID,pair[3]))
        p1s = get_skill_list(p1[8])
        p1i = get_skill_list(p1[9])
        p2s = get_skill_list(p2[8])
        p2i = get_skill_list(p2[9])
        p3s = get_skill_list(p3[8])
        p3i = get_skill_list(p3[9])

        p1[8] = ', '.join([f'<i><b>{x}</b></i>' if x in p2i+p3i else x for x in p1s])
        p1[9] = ', '.join([f'<i><b>{x}</b></i>' if x in p2s+p3s else x for x in p1i])
        p2[8] = ', '.join([f'<i><b>{x}</b></i>' if x in p1i+p3i else x for x in p2s])
        p2[9] = ', '.join([f'<i><b>{x}</b></i>' if x in p1s+p3s else x for x in p2i])
        p3[8] = ', '.join([f'<i><b>{x}</b></i>' if x in p1i+p2i else x for x in p3s])
        p3[9] = ', '.join([f'<i><b>{x}</b></i>' if x in p1s+p2s else x for x in p3i])


        if p1[4] == p2[4]:
            p1[4] = f'<i><b>{p1[4]}</b></i>'
            p2[4] = f'<i><b>{p2[4]}</b></i>'
        if p1[4] == p3[4]:
            p1[4] = f'<i><b>{p1[4]}</b></i>'
            p3[4] = f'<i><b>{p3[4]}</b></i>'
        if p2[4] == p3[4]:
            p2[4] = f'<i><b>{p2[4]}</b></i>'
            p3[4] = f'<i><b>{p3[4]}</b></i>'

        return (pair[0], p1, p2, p3)
    
    else:
        p1 = list(get_user_from_sid(eventID,pair[1]))
        p2 = list(get_user_from_sid(eventID,pair[2]))
        p1s = get_skill_list(p1[8])
        p1i = get_skill_list(p1[9])
        p2s = get_skill_list(p2[8])
        p2i = get_skill_list(p2[9])

        p1[8] = ', '.join([f'<i><b>{x}</b></i>' if x in p2i else x for x in p1s])
        p1[9] = ', '.join([f'<i><b>{x}</b></i>' if x in p2s else x for x in p1i])
        p2[8] = ', '.join([f'<i><b>{x}</b></i>' if x in p1i else x for x in p2s])
        p2[9] = ', '.join([f'<i><b>{x}</b></i>' if x in p1s else x for x in p2i])

        if p1[4] == p2[4]:
            p1[4] = f'<i><b>{p1[4]}</b></i>'
            p2[4] = f'<i><b>{p2[4]}</b></i>'

        return (pair[0], p1, p2)


def populate_compatibility(participants):

    compatibility = {}
    for person in participants:
        sid = person[0]
        compatibility[sid] = {}
        total_skills = len(get_skill_index_list(person[8]))
        total_interests = len(get_skill_index_list(person[9]))
        skill_multiplier, interest_multiplier = 1/total_skills, 1/total_interests
        for i in range(len(participants)):
            if person == participants[i]:
                continue
            sid2 = participants[i][0]

            skills2 = enrich_skills(get_skill_index_list(participants[i][8]))
            interests1 = enrich_skills(get_skill_index_list(person[9]))
            compat_1_2 = calculate_compatability(skills2, interests1, interest_multiplier)

            skills1 = enrich_skills(get_skill_index_list(person[8]))
            interests2 = enrich_skills(get_skill_index_list(participants[i][9]))
            compat_2_1 = calculate_compatability(skills1, interests2, skill_multiplier)

            if add_location_bonus(person[4], participants[i][4]):
                bonus = 1 * 0.5/(total_skills+total_interests)
            else:
                bonus = 0

            compatibility[sid][sid2] = compat_1_2 + compat_2_1 + bonus
    
    avrs = {}
    for p, d in compatibility.items():
        for other, score in d.items():
            if avrs.get((p, other)) or avrs.get((other, p)):
                continue
            s = round((compatibility[other][p] + score)/2,3)
            avrs[(p,other)] = s
    
    results = {k: v for k, v in sorted(avrs.items(), key=lambda item: item[1], reverse=True)}

    final_results = []
    found = set()
    if len(participants) % 2 == 0:     
        total = len(participants)
        odd = False
    else:
        total = len(participants) - 1
        odd = True
    for r in results.keys():
        if len(found) >= total:
            break
        if r[0] in found or r[1] in found:
            continue
        final_results.append((results[r], r[0], r[1]))
        found.add(r[0])
        found.add(r[1])
    
    if odd:
        p_set = set([x[0] for x in participants])
        missing = set_pop(p_set.difference(found))
    else:
        missing = None
    
    return final_results, missing

def find_group(groups, extra, eventID):
    
    ex = get_user_from_sid(eventID, extra)
    ex_skills = enrich_skills(get_skill_index_list(ex[8]))
    ex_interests = enrich_skills(get_skill_index_list(ex[9]))

    compatabilities = []
    for i, g in enumerate(groups):
        p1 = get_user_from_sid(eventID, g[1])
        p2 = get_user_from_sid(eventID, g[2])
        all_skills = tuple(set(get_skill_index_list(p1[8]) + (get_skill_index_list(p2[8]))))
        all_interests = tuple(set(get_skill_index_list(p1[9]) + (get_skill_index_list(p2[9]))))
        skill_multiplier, interest_multiplier = 1/len(all_skills), 1/len(all_interests)
        compat_g_ex = calculate_compatability(all_interests, ex_skills, interest_multiplier)
        compat_ex_g = calculate_compatability(all_skills, ex_interests, skill_multiplier)
        if compat_g_ex == 0: compat_g_ex = -1
        if compat_ex_g == 0: compat_ex_g = -1
        bonus = 0
        if add_location_bonus(p1[4], ex[4]):
            bonus += 1 * 0.25/(len(all_skills)+len(all_interests))
        if add_location_bonus(p2[4], ex[4]):
            bonus += 1 * 0.25/(len(all_skills)+len(all_interests))
        total = round(compat_g_ex + compat_ex_g + bonus, 3)
        
        compatabilities.append((i, (g[1],g[2]), total))
    
    compatabilities.sort(key=lambda item: item[2], reverse=True)

    return compatabilities[0]


def set_pop(s):
    for e in s:
        break
    return e


def calculate_compatability(skills, interests, multiplier):

    compatability = 0
    first_match_bonus = 1

    for skill in skills:
        for interest in interests:
            if skill[0] == interest[0]:
                if interest[3] == 'Y':
                    compatability += 5 * multiplier + first_match_bonus
                    first_match_bonus = 0
                elif skill[3] == 'Y':
                    compatability += 2 * multiplier + first_match_bonus
                    first_match_bonus = 0
                else:
                    compatability += 1 * multiplier + first_match_bonus
                    first_match_bonus = 0
    
    return compatability


def add_location_bonus(location1, location2):

    if location1 == location2:
        return True
    return False


def enrich_skills(skill_indexes):
    enriched_skills = []
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        for index in skill_indexes:
            cur.execute(
                "SELECT * FROM ALL_INTERESTS "
                "WHERE INTEREST_ID=?;",
                (index,)
            )
            r = cur.fetchone()
            if r:
                enriched_skills.append(tuple(r))  
    return enriched_skills         


def remove_participant(eventID, SID):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM SIGNUPS "
            "WHERE EVENT_ID=? "
            "AND SID=?;",
            (eventID,SID)
        )
        conn.commit()

def get_user_inputs(form):

    sid = form.get("sid")
    name = form.get("name")
    email = form.get("email")
    location = form.get("location")
    title = form.get("title")
    lob = form.get("lob")
    team = form.get("team")

    skills_input = form.get("selected_skills_data")
    interests_input = form.get("selected_interests_data")

    if skills_input:
        skills_list = skills_input[:-1].split("|")
        skills = "|".join(["//".join(x) for x in [get_interest_id_from_name(s) for s in skills_list]])
    else:
        skills = None

    if interests_input:
        interests_list = interests_input[:-1].split("|")
        interests = "|".join(["//".join(x) for x in [get_interest_id_from_name(i) for i in interests_list]])
    else:
        interests = None

    return sid, name, email, location, title, lob, team, skills, interests

def get_interest_id_from_name(interest_name):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT INTEREST_ID, NAME "
            "FROM ALL_INTERESTS "
            "WHERE NAME=?;",
            (interest_name,)
        )
        interest = (str(x) for x in cur.fetchone())
        return interest

def get_event_details(eventID):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT EVENT_NAME, HOST_LOCATION, OPEN_TO, "
            "HOST_SID, HOST_LOCATION, START_DATE, END_DATE "
            "FROM EVENTS "
            "WHERE EVENT_ID = ?;",
            (eventID,)
        )
        event = cur.fetchone()
    
    return event

def get_signup_count(eventID):

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) "
            "FROM SIGNUPS "
            "WHERE EVENT_ID = ?;",
            (eventID,)
        )
        count = cur.fetchone()[0]
    
    return count


def get_events():

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT EVENT_ID, EVENT_NAME, START_DATE, END_DATE FROM EVENTS "
            "WHERE DATE('now') < END_DATE "
            "ORDER BY END_DATE ASC;"
        )
        res = cur.fetchall()
    return res


def validate_register(eventID, sid, email, location, skills, interests):
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        message = []

        cur.execute(
            "SELECT SID FROM SIGNUPS WHERE EVENT_ID=? AND SID=? LIMIT 1;",
            (eventID, sid)
        )
        r = cur.fetchone()
        if r:
            message.append(f"SID '{sid}' already signed up for this session")

        # Validate eventID
        cur.execute(
            "SELECT EVENT_NAME FROM EVENTS WHERE EVENT_ID = ? LIMIT 1;",
            (eventID,)
        )
        r = cur.fetchone()
        if not r:
            message.append(f"Could not find event with ID '{eventID}'")
        
        # Validate email
        if not validate_email(email):
            message.append(f"Could not validate email - '{email}'")
        
        # Validate location
        if not location:
            message.append(f"Please enter location")
        elif location.lower() == 'location':
            message.append(f"Please enter location")

        # Validate skills and interests
        if not skills:
            message.append(f"Please enter skills")
        if not interests:
            message.append(f"Please enter interests")
        
        
        return (message==[], message)


def validate_email(email):

    if not email:
        return False
    if not re.match(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)", email):
        return False
    return True
    

def register(sid, eventID, name, email, location, title, lob, team, skills, interests):
    
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO SIGNUPS "
            "(SID, EVENT_ID, NAME, EMAIL, LOCATION, JOB_TITLE, LOB, TEAM, SKILLS, INTERESTS, SIGNUP_TIME) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP);",
            (sid, eventID, name, email, location, title, lob, team, skills, interests)
        )
        conn.commit()


def get_signed_up(eventID):

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT SID, EVENT_ID, NAME, EMAIL, LOCATION, JOB_TITLE, "
            "LOB, TEAM, SKILLS, INTERESTS, SIGNUP_TIME "
            "FROM SIGNUPS WHERE EVENT_ID=?;",
            (eventID,)
        )
        res = cur.fetchall()

    return res

def get_user_from_sid(eventID, sid):

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT SID, EVENT_ID, NAME, EMAIL, LOCATION, JOB_TITLE, "
            "LOB, TEAM, SKILLS, INTERESTS, SIGNUP_TIME "
            "FROM SIGNUPS WHERE EVENT_ID=? AND SID=?;",
            (eventID,sid)
        )
        res = cur.fetchone()
    
    return res

def get_users_from_sid_list(eventID, sid_list):

    questionmarks = '?' * len(sid_list)
    formatted_query =  ("SELECT SID, EVENT_ID, NAME, EMAIL, LOCATION, JOB_TITLE, "
                        "LOB, TEAM, SKILLS, INTERESTS, SIGNUP_TIME "
                        "FROM SIGNUPS WHERE EVENT_ID=? AND SID IN ({});").format(','.join(questionmarks))
    query_args = [eventID]
    query_args.extend(sid_list)

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute(formatted_query, query_args)
        res = cur.fetchall()
    
    return res

def get_skill_index_list(skill_store_str):
    return [x.split("//")[0] for x in skill_store_str.split("|")]

def get_skill_list(skill_store_str):
    return [x.split("//")[1] for x in skill_store_str.split("|")]

def get_skill_string(skill_store_str):
    return ", ".join(get_skill_list(skill_store_str))

#Unused
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def safeget(dct: dict, *keys):
    """
    Safely gets key from possibly nested dictionary with error trapping and
    logging failures.
    """
    for key in keys:
        try:
            dct = dct[key]
        except KeyError:
            logging.warning(f"Safeget failed to find key '{key}' in dict")
            return None
        except Exception as e:
            logging.warning(f"Error in dictionary key search - {e}")
            return None
    return dct


if __name__ == "__main__":
    app.run(debug=True)
