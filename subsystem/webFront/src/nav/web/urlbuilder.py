"""
$Id$

This file is part of the NAV project.

Generate URLs to different parts of NAV based
on different criteria.

Copyright (c) 2003 by NTNU, ITEA nettgruppen
Authors: Stian S�iland <stain@itea.ntnu.no>
"""

import forgetHTML as html
import forgetSQL
from nav.db import manage 

_subsystems = {
    'devbrowser': '/browse', 
    'report': '/report',
    'rrd': '/rrd/rrdBrowser',
}

_divisionClasses = {
    'service': manage.Service,
    'room': manage.Room,
    'org': manage.Org,
    'netbox': manage.Netbox,
    'cat': manage.Cat,
    'type': manage.Type,
    'location': manage.Location,
}

def _getObjectByDivision(division, id):
    try:
        _class = _divisionClasses[division]
    except KeyError:
        raise "Unknown division: %s" % division
    object = _class(id)
    try:
        object.load()
    except forgetSQL.NotFound, e:
        raise "Unknown id %s" % e
    return object           

def _getDivisionByObject(object):
    for (division, _class) in _divisionClasses.items():
        if isinstance(object, _class):
            return division
    raise "Unknown division"        

def createUrl(object=None, id=None, division=None, 
              subsystem="devbrowser", mode="view", **kwargs):
    try:
        url = _subsystems[subsystem] + '/'
    except KeyError:
        raise "Unknown subsystem: %s" % subsystem
    if id and object:
        raise "Ambiguous parameters, id and object cannot both be specified"


    if subsystem == 'devbrowser':
        if id and division not in ('service',):
            object = _getObjectByDivision(division, id)
        if not division and object:
            try:
                division = _getDivisionByObject(object)
            except:
                raise "Unknown object type"
        if division:
            if not (subsystem == 'devbrowser' and division=='netbox'):
                url += division + '/'
            if id and subsystem=='devbrowser' and division=='service':
               url += id + '/'
               return url
            if object:
                try:
                    # Does it exist in the database?
                    object.load()
                except forgetSQL.NotFound, e:
                    raise "Unknown id %s" % e
                if division=="netbox":    
                    # We skip the redirect
                    url += object.sysname
                else:
                    # Turn into strings, possibly join with ,
                    id = [str(x) for x in object._getID()]
                    url += ','.join(id)
                url += '/' # make sure we have trailing /    

    elif subsystem == 'rrd':
        # M�KKAKODEDRITFAEN!
        url += division
        url += '?'
        if type(id) != list:
            # since id might be a list, we always treat
            # it as a list.
            id = [id]
        for i in id:
            url += 'id=%s&amp;' % i
        tf = kwargs.get("tf")
        if tf:
            url += 'tf=%s' % tf
    return url            
            
    
def createLink(object=None, content=None, id=None, division=None,
               subsystem="devbrowser", mode="view", **kwargs):
    if content is None:
        if id and object:
            raise "Ambiguous parameters, id and object cannot both be specified"
        if division == 'service':
            content = id
        elif id:    
            object = _getObjectByDivision(division, id)
            id = None
        if object:    
            content = str(object)    
    url = createUrl(id=id, division=division, subsystem=subsystem,
                    mode=mode, object=object, **kwargs)
    return html.Anchor(content, href=url)                
           
            
        
