from daemon import Daemon
import os
import gearman
from vagrant import Vagrant
import logging
import sys

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.FileHandler('vagrant-worker.log')
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class App(Daemon):
    def run(self):
        while True:
            gm_worker = gearman.GearmanWorker(['localhost'])
            gm_worker.set_client_id('vagrant-worker-{}'.format(os.getpid()))
            logger.info('Registering gearman vagrant-worker-{}'
                        .format(os.getpid()))
            gm_worker.register_task('start', run)
            gm_worker.register_task('stop', stop)
            gm_worker.register_task('status', status)
            gm_worker.work()


def run(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.info('Bring up {}'.format(path))

    vagrant = Vagrant(path)
    vagrant.up()
    logger.info('Done bring up {}'.format(path))

    return _get_status(vagrant)


def stop(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.info('Bring down {}'.format(path))

    vagrant = Vagrant(path)
    vagrant.halt()
    logger.info('Done bring down {}'.format(path))
    return _get_status(vagrant)


def status(gearman_worker, gearman_job):
    path = _get_path(gearman_job)
    logger.info('Asking Status for {}'.format(path))

    vagrant = Vagrant(path)
    status = _get_status(vagrant)
    logger.info('Status : {} :: {}'.format(status, path))
    return _get_status(vagrant)


def _get_path(gearman_job):
    return gearman_job.data


def _get_status(vagrant):
    statuses = vagrant.status()
    return ''.join([status + '::' + statuses[status] for status in statuses])


if __name__ == '__main__':
    #app = App('/var/run/vagrant-worker.pid'.format(os.getpid()))
    app = App('vagrant-worker.pid')
    if len(sys.argv) == 2:
        if 'start' == sys.argv[1]:
            logger.info('Starting vagrant-worker service')
            app.start()
        elif 'stop' == sys.argv[1]:
            logger.info('Stopping vagrant-worker service')
            app.stop()
        elif 'restart' == sys.argv[1]:
            logger.info('Restart vagrant-worker service')
            app.restart()
        else:
            print 'Unknown command'
            sys.exit(0)
    else:
        print 'usage: {} start|stop|restart '.format(sys.argv[0])
        sys.exit(2)
