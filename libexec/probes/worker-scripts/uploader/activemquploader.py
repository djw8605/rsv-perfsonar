from uploader import *

# Need to push to cern message queue                                                                                                                
                               
from messaging.message import Message
from messaging.queue.dqs import DQS

class ActiveMQUploader(Uploader):
    
    def __init__(self, start = 1600, connect = 'iut2-net3.iu.edu', metricName='org.osg.general-perfsonar-simple.conf'):
        Uploader.__init__(self, start, connect, metricName)
        self.maxMQmessageSize =  self.readConfigFile('mq-max-message-size')
        #Code to allow publishing data to the mq                                                                                                                
        self.mq = None
        self.dq = self.readConfigFile('directoryqueue')
        self.granularity = int(self.readConfigFile('granularity'))
        if self.dq != None and self.dq!='None':
            try:
                self.mq = DQS(path=self.dq, granularity=self.granularity)
            except Exception as e:
                self.add2log("Unable to create dirq %s, exception was %s, " % (self.dq, e))


    # Publish summaries to Mq
    def publishSToMq(self, arguments, event_types, summaries, summaries_data):
        # the max size limit in KB but python expects it in bytes
        size_limit = self.maxMQmessageSize * 1000
        for event in summaries_data.keys():
            if not summaries_data[event]:
                continue
            msg_head = { 'input-source' : arguments['input_source'],
                         'input-destination' : arguments['input_destination'],
                         'org_metadata_key' : arguments['org_metadata_key'],
                         'event-type' : event,
                         'rsv-timestamp' : "%s" % time.time(),
                         'summaries' : 1,
                         'destination' : '/topic/perfsonar.summary.' + event }
            msg_body = { 'meta': arguments }
            msg_body['summaries'] = summaries_data[event]
            size_summ = self.total_size(summaries_data[event])
            msg = Message(body=json.dumps(msg_body), header=msg_head)
            size_msg = msg.size()
            #self.add2log("Message size: %s" % size_msg)
            # if size of the message is larger than 10MB discarrd                                                                          
            if size_msg > size_limit or sys.getsizeof(json.dumps(msg_body)) > size_limit or size_summ > size_limit:
                self.add2log("Size of message body bigger than limit, discarding")
                continue
            # add to mq      
            try:
                self.mq.add_message(msg)
            except Exception as e:
                self.add2log("Failed to add message to mq %s, exception was %s" % (self.dq, e))
    
    # Publish message to Mq
    def publishRToMq(self, arguments, event_types, datapoints):
        for event in datapoints.keys():
            # filter events for mq (must be subset of the probe's filter)
            if event not in self.allowedEvents:
                continue
            # skip events that have no datapoints 
            if not datapoints[event]:
                continue
            # compose msg
            msg_head = { 'input-source' : arguments['input_source'],
                        'input-destination' : arguments['input_destination'],
                         'org_metadata_key' : arguments['org_metadata_key'],
                          # including the timestart of the smalles measureement                                                            
                         'ts_start' : min(datapoints[event].keys()),
                         'event-type' : event,
                         'rsv-timestamp' : "%s" % time.time(),
                         'summaries' : 0,
                         'destination' : '/topic/perfsonar.raw.' + event}
            msg_body = { 'meta': arguments }
            msg_body['datapoints'] = datapoints[event]
            msg = Message(body=json.dumps(msg_body), header=msg_head)
            # add to mq
            try:
                self.mq.add_message(msg)
            except Exception as e:
                self.add2log("Failed to add message to mq %s, exception was %s" % (self.dq, e))

    def postData(self, arguments, event_types, summaries, summaries_data, metadata_key, datapoints):
        summary= self.summary
        disp = self.debug
        lenght_post = -1
        arguments['org_metadata_key'] = metadata_key
        for event_type in datapoints.keys():
            if len(datapoints[event_type])>lenght_post:
                lenght_post = len(datapoints[event_type])
        if lenght_post == 0:
            self.add2log("No new datapoints skipping posting for efficiency")
            return
        if self.mq and summaries_data:
            self.add2log("posting new summaries")
            self.publishSToMq(arguments, event_types, summaries, summaries_data)
        step_size = 100
        for step in range(0, lenght_post, step_size):
            chunk_datapoints = {}
            for event_type in datapoints.keys():
                chunk_datapoints[event_type] = {}
                if len(datapoints[event_type].keys())>0:
                    pointsconsider = sorted(datapoints[event_type].keys())[step:step+step_size]
                    for point in pointsconsider:
                        chunk_datapoints[event_type][point] = datapoints[event_type][point]
            if self.mq:
                self.publishRToMq(arguments, event_types, chunk_datapoints)
                # Updating the checkpoint files for each host/metric and metadata
                for event_type in datapoints.keys():
                     if len(datapoints[event_type].keys()) > 0:
                         if event_type not in self.time_starts:
                             self.time_starts[event_type] = 0
                         next_time_start = max(datapoints[event_type].keys())+1
                         if next_time_start > self.time_starts[event_type]:
                             self.time_starts[event_type] = int(next_time_start)
                f = open(self.tmpDir + metadata_key, 'w')
                f.write(json.dumps(self.time_starts))
                f.close()
                self.add2log("posting NEW METADATA/DATA to Cern Active MQ %s" % metadata_key)
                
