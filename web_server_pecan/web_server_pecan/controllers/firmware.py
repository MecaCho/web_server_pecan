import logging
import time
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(name)s - %(message)s")
LOG = logging.getLogger(__name__)



class FirmwareStatisticsRootResponse(object):
    project_id = None
    start_time = None
    end_time = None
    count = None


def temp():
    s_time = int(time.time())
    filter_dict = {"start_time": s_time, "end_time": s_time + 24 * 60 * 60, "duration": "hour"}
    statistic = []

    offset_dict = {"hour": 60 * 60, "day": 24 * 60 * 60, "month": 30 * 24 * 60 * 60, "year": 365 * 24 * 60 * 60}
    offset = offset_dict[filter_dict["duration"]]

    ret = FirmwareStatisticsRootResponse()
    for start_t in xrange(filter_dict["start_time"], filter_dict["end_time"], offset):
        start_time, end_time = start_t, min(start_t + offset, filter_dict["end_time"])

        node_firms = [1, 2, 3]
        # query = db_session.query(models.NodeFirmware).filter_by(**query_dict)
        # query = query.filter(models.NodeFirmware.installed_at.between(start_time, end_time))
        # node_firms = query.filter(models.NodeFirmware.node_id.in_(node_ids)).all()
        LOG.info("Query by time, start_time: {}, end_time: {}, installed_at: {}".format(
                start_time, end_time, node_firms[0] if node_firms else None))
        if node_firms:
            ret.project_id = "self.project_id"
            ret.start_time = start_time
            ret.end_time = end_time
            ret.count = len(node_firms)
            statistic.append(ret.__dict__)

    LOG.info(str(statistic))

def print_res(ress):
    print "+"*100
    for i in ress:
        print i.count

if __name__ == '__main__':
    ress = []
    for i in xrange(100):
        res = FirmwareStatisticsRootResponse()
	res.count = random.randint(0,100)
        ress.append(res)
    res.count = None
    ress.append(res)
    print_res(ress)
    ress =  sorted(ress, key=lambda x: x.count, reverse=True)
    print_res(ress)
    print hasattr(res, "count")
    print hasattr(res, "_project_id")
