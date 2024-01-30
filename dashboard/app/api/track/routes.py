import uuid

from http import HTTPStatus as status

from flask import jsonify, request
from flask_jwt_extended import jwt_required

from app.api.track import bp
from app.extensions import db
from app.models.track import Track
from app.telemetry.psst import dataclass_from_dict


@bp.route('', methods=['GET'])
def get_all():
    entities = db.session.execute(db.select(Track)).scalars()
    return jsonify(list(entities)), status.OK


@bp.route('/<uuid:id>', methods=['GET'])
def get(id: uuid.UUID):
    entity = db.session.execute(
        db.select(Track).filter_by(id=id)).scalar_one_or_none()
    if not entity:
        return jsonify(msg="Track does not exist!"), status.NOT_FOUND
    return jsonify(entity), status.OK


@bp.route('/<uuid:id>', methods=['DELETE'])
@jwt_required()
def delete(id: uuid.UUID):
    db.session.execute(db.delete(Track).filter_by(id=id))
    db.session.commit()
    return '', status.NO_CONTENT


@bp.route('', methods=['PUT'])
@jwt_required()
def put():
    entity = dataclass_from_dict(Track, request.json)
    if not entity:
        return jsonify(msg="Invalid data for Track"), status.BAD_REQUEST
    entity = db.session.merge(entity)
    db.session.commit()
    return jsonify(id=entity.id), status.CREATED
