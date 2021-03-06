import logging
import itertools

from django.db import transaction

from share.bot import Bot
from share.models import Change
from share.models import ChangeSet

logger = logging.getLogger(__name__)


def chunk(iterable, size):
    return itertools.zip_longest(*([iter(iterable)] * size))


class AutoMergeBot(Bot):

    def run(self, last_run, chunk_size=50, dry=False):
        qs = ChangeSet.objects.filter(
            status=ChangeSet.STATUS.pending,
            changes__type=Change.TYPE.create,
        ).exclude(
            normalized_data__source__robot=''
        ).distinct()

        total = qs.count()
        logger.info('Found %s change sets eligible for automatic acceptance', total)
        logger.info('Committing in chunks of %d', chunk_size)

        for i, changesets in enumerate(chunk(qs.all(), chunk_size)):
            with transaction.atomic():
                for cs in changesets:
                    if not cs:
                        break
                    cs.accept()
                    logger.debug('Accepted change set %r', cs)
                logger.info('Committed %d of %d', chunk_size * (i + 1), total)
