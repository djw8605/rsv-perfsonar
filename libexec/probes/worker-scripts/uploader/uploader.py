import os
import time
import inspect
import json
import warnings
import sys
import ConfigParser
from time import strftime
from time import localtime

# Using the esmond_client instead of the rpm
from esmond_client.perfsonar.query import ApiFilters
from esmond_client.perfsonar.query import ApiConnect

# New module with socks5 OR SSL connection that inherits ApiConnect
from SocksSSLApiConnect import SocksSSLApiConnect
from SSLNodeInfo import EventTypeSSL
from SSLNodeInfo import SummarySSL

# Set filter object
filters = ApiFilters()

class Uploader(object):

    def add2log(self, log):
        print strftime("%a, %d %b %Y %H:%M:%S", localtime()), str(log)
    
    def __init__(self, start = 1600, connect = 'iut2-net3.iu.edu', metricName='org.osg.general-perfsonar-simple.conf'):
        ########################################
        ### New Section to read directly the configuration file                                                                     
        self.metricName =  metricName
        conf_dir = os.path.join("/", "etc", "rsv", "metrics")
        self.configFile = os.path.join(conf_dir, metricName + ".conf")
        self.add2log("Configuration File: %s" % self.configFile)
        self.config = ConfigParser.RawConfigParser()
        ########################################        
        self.debug = self.str2bool(self.readConfigFile('debug'))
        verbose = self.debug
        # Filter variables
        filters.verbose = verbose
        #filters.verbose = True 
        # this are the filters that later will be used for the data
        self.time_end = int(time.time())
        self.time_start = int(self.time_end - start)
        # Filter for metadata
        filters.time_start = int(self.time_end - 3*start)
        # Added time_end for bug that Andy found as sometime far in the future 24 hours
        filters.time_end = self.time_end + 24*60*60
        # For logging pourposes
        filterDates = (strftime("%a, %d %b %Y %H:%M:%S ", time.gmtime(self.time_start)), strftime("%a, %d %b %Y %H:%M:%S", time.gmtime(self.time_end)))
        #filterDates = (strftime("%a, %d %b %Y %H:%M:%S ", time.gmtime(filters.time_start)))
        self.add2log("Data interval is from %s to %s" %filterDates)
        self.add2log("Metada interval is from %s to now" % (filters.time_start))
        # Connection info to the perfsonar remote host that the data is gathered from.
        self.connect = connect
        self.conn = SocksSSLApiConnect("http://"+self.connect, filters)
        self.cert = self.readConfigFile('usercert')
        self.certkey = self.readConfigFile('userkey')
        # The tmp dir structure is: tmp/metricName/host/metadatafiles
        self.tmpDir = os.path.join(self.readConfigFile('tmpdirectory'), self.metricName, self.connect + '/')
        # Convert the allowedEvents into a list
        allowedEvents = self.readConfigFile('allowedEvents')
        self.allowedEvents = allowedEvents.split(',')
        self.useSSL = False

        self.summary = self.str2bool(self.readConfigFile('summary'))
                
    # Get Data
    def getData(self):
        disp = self.debug
        self.add2log("Only reading data for event types: %s" % (str(self.allowedEvents)))
        summary = self.summary
        disp = self.debug
        if summary:
            self.add2log("Reading Summaries")
        else:
            self.add2log("Omiting Sumaries")
        metadata = self.conn.get_metadata()
        try:
            #Test to see if https connection is succesfull
            md = metadata.next()
            self.readMetaData(md)
        except Exception as e:
            #Test to see if https connection is sucesful
            self.add2log("Unable to connect to %s, exception was %s, trying SSL" % ("http://"+self.connect, e))
            try:
                metadata = self.conn.get_metadata(cert=self.cert, key=self.certkey)
                md = metadata.next()
                self.useSSL = True
                self.readMetaData(md)
            except Exception as e:
                raise Exception("Unable to connect to %s, exception was %s, " % ("https://"+self.connect, e))
        for md in metadata:
            self.readMetaData(md)

    # Md is a metadata object of query
    def readMetaData(self, md):
        disp = self.debug
        summary = self.summary
        arguments = {}
        # Building the arguments for the post
        arguments = {
            "subject_type": md.subject_type,
            "source": md.source,
            "destination": md.destination,
            "tool_name": md.tool_name,
            "measurement_agent": md.measurement_agent,
            "input_source": md.input_source,
            "input_destination": md.input_destination,
            "tool_name": md.tool_name
        }
        if not md.time_duration is None:
            arguments["time_duration"] = md.time_duration
        if not md.ip_transport_protocol is None:
            arguments["ip_transport_protocol"] = md.ip_transport_protocol
        # Assigning each metadata object property to class variables
        event_types = md.event_types
        metadata_key = md.metadata_key
        # print extra debugging only if requested
        self.add2log("Reading New METADATA/DATA %s" % (md.metadata_key))
        if disp:
            self.add2log("Posting args: ")
            self.add2log(arguments)
        # Get Events and Data Payload
        summaries = {}
        summaries_data = {}
        # datapoints is a dict of lists
        # Each of its members are lists of datapoints of a given event_type
        datapoints = {}
        datapointSample = {}
        #load next start times
        self.time_starts = {}
        try:
            f = open(self.tmpDir+md.metadata_key, 'r')
            self.time_starts = json.loads(f.read())
            f.close()
        except IOError:
            self.add2log("first time for %s" % (md.metadata_key))
        except ValueError:
            # decoding failed
            self.add2log("first time for %s" % (md.metadata_key))
        for et in md.get_all_event_types():
            if self.useSSL:
                etSSL = EventTypeSSL(et, self.cert, self.certkey)
                et = etSSL
            # Adding the time.end filter for the data since it is not used for the metadata
            #use previously recorded end time if available
            et.filters.time_start = self.time_start
            if et.event_type in self.time_starts.keys():
                et.filters.time_start = self.time_starts[et.event_type]
                self.add2log("loaded previous time_start %s" % et.filters.time_start)
            et.filters.time_end = filters.time_end
            eventype = et.event_type
            datapoints[eventype] = {}
            #et = md.get_event_type(eventype)
            if summary:
                summaries[eventype] = et.summaries
            else:
                summaries[eventype] = []
            # Skip reading data points for certain event types to improv efficiency  
            if eventype not in self.allowedEvents:                                                                                                  
                continue
            # Read summary data 
            summaries_data[eventype] = []
            for summ in et.get_all_summaries():
                if self.useSSL:
                    summSSL = SummarySSL(summ, self.cert, self.certkey)
                    summ = summSSL
                summ_data = summ.get_data()
                summ_dp = [ (dp.ts_epoch, dp.val) for dp in summ_data.data ]
                if not summ_dp:
                    continue
                summaries_data[eventype].append({'event_type': eventype,
                                                   'summary_type' : summ.summary_type,
                                                   'summary_window' : summ.summary_window,
                                                   'summary_data' : summ_dp })
                # Read datapoints
            dpay = et.get_data()
            tup = ()
            for dp in dpay.data:
                tup = (dp.ts_epoch, dp.val)
                datapoints[eventype][dp.ts_epoch] = dp.val
                # print debugging data
            self.add2log("For event type %s, %d new data points"  %(eventype, len(datapoints[eventype])))
            if len(datapoints[eventype]) > 0 and not isinstance(tup[1], (dict,list)): 
                # picking the first one as the sample
                datapointSample[eventype] = tup[1]
        self.add2log("Sample of the data being posted %s" % datapointSample)
        try:
            self.postData(arguments, event_types, summaries, summaries_data, metadata_key, datapoints)
        except Exception as e:
            raise Exception("Unable to post because exception: %s"  % e)

    # Experimental function to try to recover from missing packet-count-sent or packet-count-lost data
    def getMissingData(self, timestamp, metadata_key, event_type):
        disp = self.debug
        filtersEsp = ApiFilters()
        filtersEsp.verbose = disp
        filtersEsp.metadata_key = metadata_key
        filtersEsp.time_start = timestamp - 30000
        filtersEsp.time_end  = timestamp + 30000 
        conn = SocksSSLApiConnect("http://"+self.connect, filtersEsp)
        if self.useSSL:
            metadata = conn.get_metadata(cert=self.cert, key=self.certkey)
        else:
            metadata = conn.get_metadata()
        datapoints = {}
        datapoints[event_type] = {}
        for md in metadata:
            if not md.metadata_key == metadata_key:
                continue
            et = md.get_event_type(event_type)
            if self.useSSL:
                etSSL = EventTypeSSL(et, self.cert, self.certkey)
                et = etSSL
            dpay = et.get_data()
            for dp in dpay.data:
                if dp.ts_epoch == timestamp:
                    self.add2log("point found")
                    datapoints[event_type][dp.ts_epoch] = dp.val
        return datapoints
                
    # Place holde for posting Data if it is to Esmond, ActiveMQ, RabbitMQ
    def postData(self, arguments, event_types, summaries, summaries_data, metadata_key, datapoints):
        pass

    def readConfigFile(self, key):
        section = self.metricName + " args"
        ret = self.config.read(self.configFile)
        try:
            return self.config.get(section, key)
        except ConfigParser.NoOptionError:
            self.add2log("ERROR: config knob %s not found in file: %s"% (self.key, self.configFile))
            raise Exception("ERROR: config knob %s not found in file: %s"% (self.key, self.configFile))
            

    def str2bool(self,word):
        return word.lower() in ("true")