import json
import logging
import datetime

import celery
import requests

from django.apps import apps
from django.conf import settings

from share.change import ChangeGraph
from share.models import RawData, NormalizedManuscript, ShareUser

logger = logging.getLogger(__name__)


@celery.task(bind=True)
def run_harvester(self, app_label, start=None, end=None, started_by=None):
    if not start and not end:
        start, end = datetime.timedelta(days=-1), datetime.datetime.utcnow()
    config = apps.get_app_config(app_label)
    harvester = config.harvester(config)

    # self.send_event('', )

    try:
        logger.info('Starting harvester run for {} {} - {}'.format(app_label, start, end))
        raws = harvester.harvest(start, end)
        logger.info('Collected {} data blobs from {}'.format(len(raws), app_label))
    except Exception as e:
        raise self.retry(countdown=10, exc=e)

    for raw in raws:
        task = run_normalizer.apply_async((app_label, raw.pk,), {'started_by': started_by})
        logger.debug('Started run_normalizer task {} for {}'.format(task, raw.id))


@celery.task(bind=True)
def run_normalizer(self, app_label, raw_id, started_by=None):
    raw = RawData.objects.get(pk=raw_id)
    config = apps.get_app_config(app_label)
    normalizer = config.normalizer(config)

    logger.info('Starting normalization for {} by {}'.format(raw, normalizer))

    try:
        graph = normalizer.normalize(raw)
    except Exception as e:
        raise self.retry(countdown=10, exc=e)

    logger.debug('Parsed {} into {}'.format(raw, json.dumps(graph, indent=2)))
    resp = requests.post(settings.API_URL + 'api/normalized/', json={
        'created_at': datetime.datetime.utcnow().isoformat(),
        'normalized_data': graph,
    }, headers={'Authorization': config.authorization()})

    if (resp.status_code // 100) != 2:
        raise self.retry(countdown=10, exc=Exception('Unable to submit change graph. Recieved {!r}, {}'.format(resp, resp.content)))

    logger.info('Successfully submitted change for {!r}'.format(raw))

    return resp.json()


@celery.task()
def make_json_patches(normalized_id, started_by_id=None):
    started_by = None
    normalized = NormalizedManuscript.objects.get(pk=normalized_id)
    if started_by_id:
        started_by = ShareUser.objects.get(pk=started_by_id)
    logger.info('{} started make JSON patches for {} at {}'.format(started_by, normalized, datetime.datetime.utcnow().isoformat()))

    print(ChangeGraph(normalized.normalized_data).change_set(normalized.source))

    logger.info('Finished make JSON patches for {} by {} at {}'.format(normalized, started_by, datetime.datetime.utcnow().isoformat()))