#/usr/bin/env python

"""
A file-like object to access a host file. Thereby granting entry to an entire
data set.
Dave Kindig and Alex Pletzer, Tech-X (2011)
This code is provided with the hope that it will be useful. 
No guarantee is provided whatsoever. Use at your own risk.
"""

import os.path
from ctypes import c_char_p, c_int, CDLL, byref
import cdms2
from cdms2.error import CDMSError
from cdms2.avariable import AbstractVariable
from cdms2.tvariable import TransientVariable
from cdms2.cdmsobj import CdmsObj
from cdms2.gsStaticVariable import StaticTransientVariable, StaticFileVariable
from cdms2.gsTimeVariable import TimeTransientVariable, TimeFileVariable
from cdms2.error import CDMSError

try:
    from pycf import libCFConfig, __path__
except:
    raise ImportError, 'Error: could not import pycf'

LIBCF = __path__[0] + '/libcf'

def open(hostfile, mode = 'r'):
    """
    Open host file
    @param hostfile host file
    @param mode valid cdms2 open file mode
    """

    outHostFile = Host(hostfile, mode)
    return outHostFile

class Host:
    """
    A LibCF/GRIDSPEC host file object. This acts as the single point of entry to
    a host file. Variables and grids can be requested solely through the Host
    object. The host object is a hybrid between a variable and file object. 
    Host relies on the libcf shared object. As such, if there is a problem
    consult http://www.unidata.ucar.edu/software/libcf/docs/libcf/ for details
    on building host files and all related GRIDSPEC files.

    @return Host class on __init__
    """

    def __init__(self, hostfile, mode = 'r'):
        """
        Constructor
        @param hostfile path to the host
        @param mode read only at the moment
        """
        
        # Data dir based on location of hostfile
        if mode in ['w', 'a']:
            raise CDMSError, MethodNotImplemented
        self.mode     = mode
        self.libcfdll = None
        self.dirname  = os.path.dirname(hostfile)
        self.uri      = hostfile
        self.id       = os.path.dirname(hostfile)
        self._status_ = 'open'

        for sosuffix in '.so', '.dylib', '.dll', '.a':
            self.libcfdll = CDLL(LIBCF + sosuffix)
            if self.libcfdll:
                break
        if self.libcfdll == None: 
            raise CDMSError, 'libcf not installed or incorrect path\n  '

        elif self._status_ == 'open':

            libcfdll = self.libcfdll

            self.hostId_ct = c_int(-1)
            self.globalId_ct = c_int(-1)

            # number of grid files
            self.nGrids = 0
            
            # number of static var files 
            self.nStatDataFiles = 0

            # number of time dependent var files 
            self.nTimeDataVariables = 0

            # number of time files
            self.nTimeSliceFilesPerVar = 0

            # Filenames
            self.timeFilenames = []
            self.statFilenames = []
            self.gridFilenames = []
            self.gridNames     = []

            self.hostFileVars = [ "timeFilenames", 
                                  "statFilenames", 
                                  "gridFilenames", 
                                  "gridNames    " ]
            
            # {'varName': fileNames}
            # fileNames is array of ngrid
            self.gridVars = {}

            # {'varName': fileNames}
            # fileNames is array of ntimes x ngrid
            self.timeDepVars = {}

            # {'varName': fileNames}
            # fileNames is array of ngrid
            self.statVars = {}

            # {coordName: gridFiles}
            self.coords = {}

            # flags checking whethed host was constructed
            self.hostFileOpened = False

            # host file name
            self.hostFilename = ""

            status = libcfdll.nccf_def_host_from_file(hostfile,
                                                   byref(self.hostId_ct))
            if status != 0:
                raise CDMSError, \
                    "ERROR: not a valid host file (status=%d)" % \
                    (hostfile, status)

            # Attach global attrs
            libcfdll.nccf_def_global_from_file( hostfile, byref(self.globalId_ct))

            self.hostFileOpened = True
            self.hostFilename = hostfile

            i_ct = c_int()
            status = libcfdll.nccf_inq_host_ngrids(self.hostId_ct, byref(i_ct))
            self.nGrids = i_ct.value
            status = libcfdll.nccf_inq_host_nstatdatafiles(self.hostId_ct, byref(i_ct))
            self.nStatDataFiles = i_ct.value
            status = libcfdll.nccf_inq_host_ntimedatafiles(self.hostId_ct, byref(i_ct))
            print i_ct.value
            self.nTimeDataVariables = i_ct.value
            status = libcfdll.nccf_inq_host_ntimeslices(self.hostId_ct, byref(i_ct))
            self.nTimeSliceFilesPerVar = i_ct.value

            varName_ct = c_char_p(" " * (libCFConfig.NC_MAX_NAME+1))
            fName_ct = c_char_p(" " * (libCFConfig.NC_MAX_NAME+1))

            self.dimensions = {"nGrids": self.nGrids, "nStatDataFiles": self.nStatDataFiles, \
                               "nTimeDataVariables": self.nTimeDataVariables, \
                               "nTimeSliceFilesPerVar":self.nTimeSliceFilesPerVar }

            # Mosaic filename (use getMosaic to return the connectivity)
            mosaicFilename = c_char_p(" " * (libCFConfig.NC_MAX_NAME + 1))
            status = libcfdll.nccf_inq_host_mosaicfilename(self.hostId_ct, mosaicFilename)
            self.mosaicFilename = mosaicFilename.value

            coordinates = []

            # static data
            for vfindx in range(self.nStatDataFiles):
                for gfindx in range(self.nGrids):
                    status = libcfdll.nccf_inq_host_statfilename(self.hostId_ct, 
                                                              vfindx, gfindx, 
                                                              fName_ct)
                    am=0
                    self.statFilenames.append(fName_ct.value)
                    f = cdms2.open(fName_ct.value, 'r')
                    varNames = f.listvariable()

                    for vn in varNames:
                        # Add coordinate names a local list of coordinates
                        if 'coordinates' in dir(f[vn]):
                            for coord in f[vn].coordinates.split():
                                if not coord in coordinates: coordinates.append(coord)
                        if not self.statVars.has_key(vn):
                            # allocate
                            self.statVars[vn] = ["" for ig in range(self.nGrids)] 

                        # set file name
                        self.statVars[vn][gfindx] = fName_ct.value
                    f.close()

            # time dependent data
            for vfindx in range(self.nTimeDataVariables):
                for tfindx in range(self.nTimeSliceFilesPerVar):
                    for gfindx in range(self.nGrids):
                        status = libcfdll.nccf_inq_host_timefilename(self.hostId_ct, 
                                                                  vfindx, tfindx, gfindx, 
                                                                  fName_ct)
                        self.timeFilenames.append(fName_ct.value)
                        f = cdms2.open(fName_ct.value, 'r')
                        varNames = f.listvariable()
                        # Add coordinate names a local list of coordinates
                        if 'coordinates' in dir(f[vn]):
                            for coord in f[vn].coordinates.split():
                                if not coord in coordinates: coordinates.append(coord)
                        for vn in varNames:
                            if not self.timeDepVars.has_key(vn):
                                # allocate
#                                self.timeDepVars[vn] = [["" for ig in range(self.nGrids)] \
#                                                            for it in range(self.nTimeSliceFilesPerVar)]
                                self.timeDepVars[vn] = [["" for it in range(self.nTimeSliceFilesPerVar)] \
                                                            for ig in range(self.nGrids)]
                            # set file name
                            self.timeDepVars[vn][gfindx][tfindx] = fName_ct.value
                        f.close()

            # Grid names and data
            for gfindx in range(self.nGrids):
                status = libcfdll.nccf_inq_host_gridfilename(self.hostId_ct, 
                                                          gfindx, 
                                                          fName_ct)
                self.gridFilenames.append(fName_ct.value)

                varNames = cdms2.open(fName_ct.value, 'r').listvariable()
                for vn in varNames:
                    if not self.gridVars.has_key(vn) and vn in coordinates:
                        # allocate
                        self.gridVars[vn] = ["" for ig in range(self.nGrids)] 
                    else:   
                        continue

                    # set file name
                    self.gridVars[vn][gfindx] = fName_ct.value

                # Get the grid names
                status = libcfdll.nccf_inq_host_gridname(self.hostId_ct, 
                                                          gfindx, 
                                                          fName_ct)
                self.gridNames.append(fName_ct.value)

          ## now close the host file NOT HERE. USE __del__
          #status = libcfdll.nccf_free_host(self.hostId_ct)
    
    def listhostfilevars(self):
        """
        Return the variables contained in the host file. These are referenced
        to create grids or variables and are attributes in the host object
        @return list of variable names
        """
        return self.hostFileVars

    def getMosaic(self):
        """
        Get the mosaic filename
        @return mfn Mosaic filename
        """
        from gsMosaic import Mosaic
        mfn = Mosaic(self.mosaicFilename, "r")

        return mfn

    def writeMosaic(self):
        """
        Write a mosaic file from tiles and data stored in self.
        """
        raise CDMSError, "Method Not Implemented"

    def getCoordinates(self, gindx):
        """
        Given a grid Index return the coordinates of that grid
        @param gindx Grid index
        @return coordinates list of coordinates
        """
        gridFile = cdms2.open(self.gridFilenames[gindx])
        c = []
        for i in range(len(self.coordinates)):
          c.append(gridFile(self.coordinates[i]))

        return c
    
    def getLatitude(self, gindx):
        """
        Given a grid Index return the coordinates of that grid
        @param gindx Grid index
        @return coordinates list of coordinates
        """
        gridFile = cdms2.open(self.gridFilenames[gindx])
        for i in range(len(self.coordinates)):
          crd = gridFile(self.coordinates[i])
          if crd.hasattr(UNITS):
            from re import search
            # Look for some form of degrees_north
            if search('degree', crd.units) and search('[nN]', crd.units):
                gridFile.close()
                return crd

    def getLongitude(self, gindx):
        """
        Given a grid Index return the coordinates of that grid
        @param gindx Grid index
        @return coordinates list of coordinates
        """
        gridFile = cdms2.open(self.gridFilenames[gindx])
        for i in range(len(self.coordinates)):
          crd = gridFile(self.coordinates[i])
          if crd.hasattr(UNITS):
            from re import search
            # Look for some form of degrees_east
            if search('degree', crd.units) and search('[eE]', crd.units):
                return crd

    def getNumGrids(self):
        """
        Get number of grids (tiles)
        @return number of grids
        """
        return len(self.gridFilenames)

    def getNumStatDataFiles(self):
        """
        Get number of static data files 
        @return number static files
        """
        return self.nStatDataFiles

    def getNumTimeDataFiles(self):
        """
        Get number of time dependent data files
        @return number time data files
        """
        return self.nTimeDataVariables

    def listvariable(self, gstype = None):
        """
        @param type Grid, Static, Time Dependent or None
        @return list of all variables, including static and time dependent, Default = None
        """
        isNone = gstype is None
        isStr = isinstance(gstype, str)

        if isNone:
            self.vars = self.gridVars.keys()
            for item in self.statVars.keys(): 
                if not item in self.vars: self.vars.append(item)
            for item in self.timeDepVars.keys(): 
                if not item in self.vars: self.vars.append(item)
            return self.vars

        elif isStr:
            if gstype.upper() == "STATIC":
                return self.statVars.keys()
            if gstype.upper() == "GRID":
                return self.gridVars.keys()
            if gstype.upper() == "TIME" or gstype.upper() == "TIMEDEP":
                return self.timeDepVars.keys()
            return None

        # Raise error
        else:
            text = "type must be  \"Grid\",\"Static\",\"Time\",\"TimeDep\", None or empty"
            raise CDMSError, text

    def listvariables(self, type = None):
        """
        Synonymous to listvariable
        @param type Grid, Static, Time Dependent or None
        @return list of all variables, including static and time dependent
        """
        return self.listvariable(type)

    def listattribute(self, varName):
        """
        List the given variables attributes
        @param varName variable name
        @return attributes list
        """
        fName = ""
        if self.statVars.has_key(varName):
            fName = self.statVars[varName][0]
        elif self.timeDepVars.has_key(varName):
            fName = self.timeDepVars[varName][0][0]
        if fName:
            var = cdms2.open(fName, 'r')(varName)
            return var.listattributes()
        else:
            return []

    def listattributes(self, varName):
        """
        Synonymous to listattribute
        @param varName variable name
        @return attributes list
        """
        return self.listattribute(varName)

    def listdimension(self):
        """
        List a variable's dimensions
        @return [nGrids, (n0, n1, ...)]
        """
        return self.dimensions.keys()
        
    def listglobal(self, attName = ""):
        """
        List global attributes of host file
        @param [attName] - Optional attribute to get a value
        @return list 
        """ 

        natts = c_int(-1)
        self.global_atts = {}
        attName_ct = c_char_p(" " * (libCFConfig.NC_MAX_NAME+1))
        attValu_ct = c_char_p(" " * (libCFConfig.NC_MAX_NAME+1))
        self.libcfdll.nccf_inq_global_natts( self.globalId_ct, byref(natts))
        for i in range(natts.value):
            self.libcfdll.nccf_inq_global_attval(self.globalId_ct, i, attName_ct, attValu_ct)
            if not self.global_atts.has_key( attName_ct.value ):
                self.global_atts[attName_ct.value] = attValu_ct.value

        if attName == "":
            return self.global_atts.keys()
        elif self.global_atts.has_key(attName):
            return (attName, self.global_atts[attName])

    def showglobal(self, attName = ""):
        """
        synonymous to listglobal
        @param [attName] - Optional attribute to get a value
        @return list 
        """
        return self.listglobal()

    def addglobal(self, name, value):
        """
        Add a global attribute to a file
        @param name attribute name
        @param value attribute value
        @return status 0 if valid
        """
        status = self.libcfdll.nccf_add_global_att( self.globalId_ct, name, value)
        return status

    def addfiletohost(self, filename):
        """
        Using libcf, add a file name to the host file
        @param filename file to be added
        @return status 0 if valid return
        """
        status = self.libcfdll.nccf_add_host_file(self.hostId_ct, filename)
        return status

    def close(self):
        """
        Close the file
        """
        self.variables = {}
        self.axes = {}
        self.grids = {}
        self._status_ = 'closed'

    def __repr__(self): 
        """
        Python repr()
        @return res Print statement
        """
        res = "< '%s',  URI: '%s', MODE: '%s', STATUS: '%s',\n libcf: %s >" % \
            ( self.__class__, self.uri, self.mode, self._status_, self.libcfdll)
        return res 

    def __del__(self):
        """
        Free the host file from memory
        """
        self.libcfdll.nccf_free_host( self.hostId_ct )

#    def __call__(self, varName):
#        """
#        The returned variable is a list of cdms2.transientVariables
#        var[nGrids][[nTimes, nz], ny,  nx]
#        Note that for nTimes, the time across files are concatenated together
#        @param varName name of variable
#        @return aggregated transient variable
#
#        example: f = filename
#                 h = cdms2.open)
#                 h.listvariables()
#                 v = h('varname')
#        """
#
#        if self.statVars.has_key(varName):
#            staticTV = StaticTransientVariable(self, varName)
#
##            return staticFV.vars 
#            return staticTV
#
#        # Time variables
#        elif self.timeDepVars.has_key(varName):
#            timeVariables = TimeTransientVariable(self, varName)
#            
##            return timeVariables.vars
#            return timeVariables
#        return self.__getitem__(varName)

    def __getitem__(self, varName):
        """

        The returned variable is a list of cdms2.fileVariables
        Equivalent to self[varName]
        @varName variable name
        @return aggregated File variable

        NOTE:
        Currently returns a transient variable. File variable needs still to
        be implemented
        example: f = filename
                 h = cdms2.open)
                 h.listvariables()
                 v = h['varname']
        """
        # Static variables
        if self.statVars.has_key(varName):
            staticFV= StaticFileVariable(self, varName)

#            return staticTV.vars 
            return staticFV

        # Time variables
        elif self.timeDepVars.has_key(varName):
            timeVariables = TimeFileVariable(self, varName)
            
#            return timeVariables.vars
            return timeVariables
    
##############################################################################

def test():
    import sys
    """
    A path to the host file must be present. This also assumes that
    the data are in the same directory as the host file.
    """
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option("-f", "--file", dest="hostFilename",
                  help="host file name")

    options, args = parser.parse_args()
    if not options.hostFilename:
        print "need to provide a host file, use -h to get a full list of options"
        sys.exit(1)

    print 'open file..., create grdspec file object...'
    gf = cdms2.open(options.hostFilename)
    if gf._status_ == 'closed': 
        print "File not opened"
        sys.exit(1)
    print 
    print "type=", type(gf)
    print 'listvariable...'
    print gf.listvariable()
    print 'listattributes...'
    print gf.listattribute('distance')
    print gf.listattribute('v')
    print 'listglobals...'
    print gf.listglobal()
    print 'print...'
    print gf
    print 'access static data...', 'distance' in gf.listvariable()
    print type(gf['distance'])
    di = gf['distance']
    print di[0].size
    print gf['distance'][0].shape
    print 'acess time dependent data...', "V" in gf.listvariables()
    print gf['V'][0].size


    # Test the mosaic
    print 'getMosaic...', 'getMosaic' in dir(gf)
    mosaic = gf.getMosaic()
    for c in mosaic.coordinate_names: print c
    for t in mosaic.tile_contacts: print "%s -> %s" % (t, mosaic.tile_contacts[t])

##############################################################################

if __name__ == "__main__": test()
