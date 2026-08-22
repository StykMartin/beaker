# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import re

import six
from flask import jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from bkr.server.app import app
from bkr.server.database import session
from bkr.server.flask_util import (
    BadRequest400,
    NotFound404,
    admin_auth_required,
    convert_internal_errors,
    json_collection,
    read_json_request,
)
from bkr.server.model import Key
from bkr.server.util import absolute_url

_KEY_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9:._-]+$')


def _serialize_key_type(key):
    return {
        'key_name': key.key_name,
        'numeric': bool(key.numeric),
    }


def _get_key_type(key_name):
    try:
        return Key.by_name(key_name)
    except NoResultFound:
        raise NotFound404('Key type %s does not exist' % key_name)


def _validate_key_name(key_name):
    if not isinstance(key_name, six.string_types) or not key_name:
        raise BadRequest400('Key type name must be a non-empty string')
    if len(key_name) > 50:
        raise BadRequest400('Key type name must be at most 50 characters')
    if not _KEY_NAME_PATTERN.match(key_name):
        raise BadRequest400('Key type name %s must match %s'
                            % (key_name, _KEY_NAME_PATTERN.pattern))
    return key_name


def _validate_numeric(numeric):
    if not isinstance(numeric, bool):
        raise BadRequest400('numeric must be true or false')
    return numeric


@app.route('/keytypes', methods=['GET'])
def get_key_types():
    query = Key.query.order_by(Key.key_name)
    result = json_collection(query, columns={
        'key_name': Key.key_name,
        'numeric': Key.numeric,
    })
    result['entries'] = [_serialize_key_type(key) for key in result['entries']]
    return jsonify(result)


@app.route('/keytypes/<key_name>', methods=['GET'])
def get_key_type(key_name):
    return jsonify(_serialize_key_type(_get_key_type(key_name)))


@app.route('/keytypes', methods=['POST'])
@admin_auth_required
def create_key_type():
    data = read_json_request(request)
    if 'key_name' not in data:
        raise BadRequest400('Missing key_name key')
    key_name = _validate_key_name(data['key_name'])
    numeric = _validate_numeric(data.get('numeric', False))
    if Key.query.filter_by(key_name=key_name).count():
        raise BadRequest400('Key type %s already exists' % key_name)
    with convert_internal_errors():
        key = Key(key_name=key_name, numeric=numeric)
        session.add(key)
    response = jsonify(_serialize_key_type(key))
    response.status_code = 201
    response.headers.add('Location', absolute_url('/keytypes/%s' % key.key_name))
    return response


@app.route('/keytypes/<key_name>', methods=['PATCH'])
@admin_auth_required
def update_key_type(key_name):
    key = _get_key_type(key_name)
    data = read_json_request(request)
    with convert_internal_errors():
        if 'key_name' in data:
            new_name = _validate_key_name(data['key_name'])
            if new_name != key.key_name and \
                    Key.query.filter_by(key_name=new_name).count():
                raise BadRequest400('Key type %s already exists' % new_name)
            key.key_name = new_name
        if 'numeric' in data:
            key.numeric = _validate_numeric(data['numeric'])
    return jsonify(_serialize_key_type(key))


@app.route('/keytypes/<key_name>', methods=['DELETE'])
@admin_auth_required
def delete_key_type(key_name):
    key = _get_key_type(key_name)
    with convert_internal_errors():
        session.delete(key)
    return '', 204
