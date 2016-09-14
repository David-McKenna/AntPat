import math
import numpy
import numpy.ma
from scipy.interpolate import RegularGridInterpolator
import matplotlib.pyplot as plt
from pntsonsphere import sph2crtISO, crt2sphHorizontal
from antpat.io.feko_ffe import FEKOffe

class TVecFields(object):
    """Provides a tangetial vector function on a spherical grid. The
    coordinates (theta,phi) should be in radians. The vector components
    can be either in polar spherical basis or in Ludwig3."""
    def __init__(self, *args):
        if len(args) > 0:
            self._full_init(*args)
    
    def _full_init(self, thetaMsh, phiMsh, F1, F2, R=None, basisType='polar'):
        self.R = R
        self.thetaMsh = thetaMsh #Assume thetaMsh is repeated columns
                                 #(unique axis=0)
        self.phiMsh = phiMsh #Assume thetaMsh is repeated rows (unique axis=1)
        if basisType == 'polar':
            self.Fthetas = F1
            self.Fphis = F2
        elif basisType == 'Ludwig3':
            #For now convert Ludwig3 components to polar spherical.
            self.Fthetas, self.Fphis = Ludwig32sph(azl, F1, F2)
        else:
            print("Error: Unknown basisType {}".format(basisType))
            exit(1)
    
    def load_ffe(self, filename, request=None):
        ffefile = FEKOffe(filename)
        if request is None:
            if len(ffefile.Requests) == 1:
                request = ffefile.Requests.pop()
            else:
                print "File contains multiple FFs (specify one): "+','.join(ffefile.Requests)
                exit(1)
        print "Request: "+request
        ffereq = ffefile.Request[request]
        self.R        = numpy.array(ffereq.freqs)
        self.thetaMsh = numpy.deg2rad(ffereq.theta)
        self.phiMsh   = numpy.deg2rad(ffereq.phi)
        nrRs= len(self.R)
        self.Fthetas = numpy.zeros((nrRs, ffereq.stheta, ffereq.sphi), dtype=complex)
        self.Fphis   = numpy.zeros((nrRs, ffereq.stheta, ffereq.sphi), dtype=complex)
        #Maybe this could be done better?
        #Convert list over R of arrays over theta,phi to array over R,theta,phi
        for ridx in range(nrRs):
            self.Fthetas[ridx,:,:] = ffereq.etheta[ridx]
            self.Fphis[  ridx,:,:] = ffereq.ephi[ridx]
    
    def getthetas(self):
      return self.thetaMsh

    def getphis(self):
      return self.phiMsh
    
    def getFthetas(self, Rval=.0):
      Rind=self.getRind(Rval)
      if Rind == None:
          return self.Fthetas
      else:
          return numpy.squeeze(self.Fthetas[Rind,...])
    
    def getFphis(self, Rval=0.):
      Rind=self.getRind(Rval)
      if Rind == None:
          return self.Fphis
      else:
          return numpy.squeeze(self.Fphis[Rind,...])
    
    def getFgridAt(self, R):
        return (self.getFthetas(R), self.getFphis(R) )
    
    def getRs(self):
      return self.R
    
    def getRind(self, Rval):
      if self.R is None or type(self.R) is float:
        return None
      Rindlst = numpy.where(self.R==Rval)
      Rind = Rindlst[0][0] #For now assume unique value.
      return Rind
    
    def getFalong(self, theta_ub, phi_ub, Rval=None):
        """Get vector field for the given direction."""
        (theta, phi) = putOnPrincBranch(theta_ub, phi_ub)
        thetaphiAxis, F_th_prdc, F_ph_prdc = periodifyRectSphGrd(self.thetaMsh,
                            self.phiMsh, self.Fthetas, self.Fphis)
        if type(self.R) is not float:
          (rM, thetaM) = numpy.meshgrid(Rval, theta, indexing='ij')
          (rM,phiM) = numpy.meshgrid(Rval, phi, indexing='ij')
          rthetaphi = numpy.zeros(rM.shape+(3,))
          rthetaphi[:,:,0] = rM
          rthetaphi[:,:,1] = thetaM
          rthetaphi[:,:,2] = phiM
          rthetaphiAxis = (self.R,)+thetaphiAxis
        else:
          rthetaphi = numpy.array([theta,phi]).T
          rthetaphiAxis = thetaphiAxis
        F_th_intrpf = RegularGridInterpolator(rthetaphiAxis, F_th_prdc)
        F_th = F_th_intrpf(rthetaphi)
        F_ph_intrpf = RegularGridInterpolator(rthetaphiAxis, F_ph_prdc)
        F_ph = F_ph_intrpf(rthetaphi)
        return F_th, F_ph
    
    def getAngRes(self):
        """Get angular resolution of mesh grid."""
        resol_th = self.thetaMsh[1,0]-self.thetaMsh[0,0]
        resol_ph = self.phiMsh[0,1]-self.phiMsh[0,0]
        return resol_th, resol_ph
      
    def sphinterp_my(self, theta, phi):
      #Currently this uses nearest value. No interpolation!
      resol_th, resol_ph  = self.getAngRes()
      ind0 = numpy.argwhere(numpy.isclose(self.thetaMsh[:,0]-theta,
                                        numpy.zeros(self.thetaMsh.shape[0]),
                                        rtol=0.0,atol=resol_th))[0][0]
      ind1 = numpy.argwhere(numpy.isclose(self.phiMsh[0,:]-phi,
                                        numpy.zeros(self.phiMsh.shape[1]),
                                        rtol=0.0,atol=resol_ph))[0][0]
      F_th = self.Fthetas[ind0,ind1]
      F_ph=  self.Fphis[ind0,ind1]
      return F_th, F_ph
    
    def rotate90z(self, sense=+1):
      self.phiMsh = self.phiMsh+sense*math.pi/2
      self.canonicalizeGrid()
    
    def canonicalizeGrid(self):
      """Put the grid into a canonical order so that azimuth goes from 0:2*pi."""
      #For now only azimuths
      #First put all azimuthals on 0:2*pi branch.
      branchNum = numpy.floor(self.phiMsh/(2*math.pi))
      self.phiMsh = self.phiMsh-branchNum*2*math.pi
      #Assume that only columns (axis=1) have to be sorted.
      i = numpy.argsort(self.phiMsh[0,:])
      self.phiMsh = self.phiMsh[:,i]
      #thetas shouldn't need sorting on columns, but F field does:
      self.Fthetas = self.Fthetas[...,i]
      self.Fphis = self.Fphis[...,i]

def periodifyRectSphGrd(thetaMsh, phiMsh, F1, F2):
    """Create a 'periodic' function in azimuth."""
    #theta is assumed to be on [0,pi] but phi on [0,2*pi[. 
    thetaAx0 = thetaMsh[:,0].squeeze()
    phiAx0 = phiMsh[0,:].squeeze()
    phiAx = phiAx0.copy()
    phiAx = numpy.append(phiAx,phiAx0[0]+2*math.pi)
    phiAx = numpy.insert(phiAx,0,phiAx0[-1]-2*math.pi)
    F1ext = numpy.concatenate((F1[...,-1:], F1, F1[...,0:1]),axis=-1)
    F2ext=numpy.concatenate((F2[...,-1:], F2, F2[...,0:1]),axis=-1)
    return (thetaAx0, phiAx), F1ext, F2ext

def putOnPrincBranch(theta,phi):
    branchNum = numpy.floor(phi/(2*math.pi))
    phi_pb = phi-branchNum*2*math.pi
    theta = numpy.abs(theta)
    branchNum = numpy.round(theta/(2*math.pi))
    theta_pb = numpy.abs(theta-branchNum*2*math.pi)
    return (theta_pb, phi_pb)


def transfVecField2RotBasis(basisto, thetas_phis_build, F_th_ph):
    """This is essentially a parallactic rotation of the transverse field."""
    thetas_build, phis_build = thetas_phis_build
    F_th, F_ph = F_th_ph
    xyz = numpy.asarray(sph2crtISO(thetas_build, phis_build))
    xyzto = numpy.matmul(basisto, xyz)
    #print("xyz", numpy.rad2deg(crt2sphHorizontal(xyz)).T)
    sphcrtMat = getSph2CartTransfMatT(xyz, ISO=True)
    sphcrtMatto = getSph2CartTransfMatT(xyzto, ISO=True)
    sphcrtMatfrom_to = numpy.matmul(numpy.transpose(basisto), sphcrtMatto)
    parRot = numpy.matmul(numpy.swapaxes(sphcrtMat[:,:,1:], 1, 2),
                        sphcrtMatfrom_to[:,:,1:])
    F_thph = numpy.rollaxis(numpy.array([F_th, F_ph]), 0, F_th.ndim+1
                           )[...,numpy.newaxis]
    F_thph_to = numpy.rollaxis(numpy.matmul(parRot, F_thph).squeeze(), -1, 0)
    return F_thph_to


def getSph2CartTransfMat(rvm, ISO=False):
    """Compute the transformation matrix from a spherical basis to a Cartesian
    basis at the field point given by the input 'r'. If input 'r' is an array
    with dim>1 then the last dimension holds the r vector components.
    The output 'transf_sph2cart' is defined such that:
    
    [[v_x], [v_y], [v_z]]=transf_sph2cart*matrix([[v_r], [v_phi], [v_theta]]).
    for non-ISO case.
    
    Returns transf_sph2cart[si,ci,bi] where si,ci,bi are the sample index,
    component index, and basis index resp.
    The indices bi=0,1,2 map to r,phi,theta for non-ISO otherwise they map to
    r,theta,phi resp., while ci=0,1,2 map to xhat, yhat, zhat resp."""
    nrOfrv = rvm.shape[0]
    rabs = numpy.sqrt(rvm[:,0]**2+rvm[:,1]**2+rvm[:,2]**2)
    rvmnrm = rvm/rabs[:,numpy.newaxis]
    xu = rvmnrm[:,0]
    yu = rvmnrm[:,1]
    zu = rvmnrm[:,2]
    rb = numpy.array([xu, yu, zu])
    angnrm = 1.0/numpy.sqrt(xu*xu+yu*yu)
    phib = angnrm*numpy.array([yu, -xu, numpy.zeros(nrOfrv)])
    thetab = angnrm*numpy.array([xu*zu, yu*zu, -(xu*xu+yu*yu)])
    if ISO:
        transf_sph2cart = numpy.array([rb, thetab, phib])
    else:
        transf_sph2cart = numpy.array([rb, phib, thetab])
    #Transpose the result to get output as stack of transform matrices.
    transf_sph2cart = numpy.transpose(transf_sph2cart, (2,1,0))
    
    return transf_sph2cart

def getSph2CartTransfMatT(rvm, ISO=False):
    """Analogous to previous but with input transposed. """
    shOfrv = rvm.shape[1:]
    dmOfrv = rvm.ndim-1
    rabs = numpy.sqrt(rvm[0]**2+rvm[1]**2+rvm[2]**2)
    rvmnrm = rvm/rabs
    xu = rvmnrm[0]
    yu = rvmnrm[1]
    zu = rvmnrm[2]
    rb = numpy.array([xu, yu, zu])
    angnrm = 1.0/numpy.sqrt(xu*xu+yu*yu)
    phib = angnrm*numpy.array([yu, -xu, numpy.zeros(shOfrv)])
    thetab = angnrm*numpy.array([xu*zu, yu*zu, -(xu*xu+yu*yu)])
    #CHECK signs of basis!
    if ISO:
        transf_sph2cart = numpy.array([rb, thetab, phib])
    else:
        transf_sph2cart = numpy.array([rb, -phib, thetab])
    #Transpose the result to get output as stack of transform matrices.
    transf_sph2cart = numpy.rollaxis(transf_sph2cart, 0, dmOfrv+2)
    transf_sph2cart = numpy.rollaxis(transf_sph2cart, 0, dmOfrv+2-1)
    return transf_sph2cart


def plotAntPat2D(angle_rad, E_th, E_ph, freq=0.5):
    fig = plt.figure()
    ax1 = fig.add_subplot(211)
    ax1.plot(angle_rad/math.pi*180,numpy.abs(E_th), label="E_th")
    ax1.plot(angle_rad/math.pi*180,numpy.abs(E_ph), label="E_ph")
    ax2 = fig.add_subplot(212)
    ax2.plot(angle_rad/math.pi*180,numpy.angle(E_th)/math.pi*180)
    ax2.plot(angle_rad/math.pi*180,numpy.angle(E_ph)/math.pi*180)
    plt.show()


def plotFEKO(filename, request=None, freq_req=None):
    """Convenience function that reads in FEKO FFE files - using load_ffe() - and
    plots it - using plotvfonsph()."""
    tvf = TVecFields()
    tvf.load_ffe(filename, request)
    freqs = tvf.getRs()
    #frqIdx = np.where(np.isclose(freqs,freq,atol=190e3))[0][0]
    if freq_req is None:
        print("")
        print("No user specified frequency (will choose first in list)")
        print("List of frequencies (in Hz):")
        print(", ".join([str(f) for f in freqs]))
        print("")
        frqIdx = 0
    else:
        frqIdx = numpy.interp(freq_req, freqs, range(len(freqs)))
    freq = freqs[frqIdx]
    print("Frequency={}".format(freq))
    (THETA, PHI, E_th, E_ph) = (tvf.getthetas(), tvf.getphis(), tvf.getFthetas(freq), tvf.getFphis(freq))
    plotvfonsph(THETA, PHI, E_th, E_ph, freq, vcoord='Ludwig3', projection='orthographic')


#TobiaC (2013-06-17)
#This function should be recast as refering to radial component instead of freq.
def plotvfonsph(theta_rad, phi_rad, E_th, E_ph, freq=0.0,
                     vcoord='sph', projection='orthographic', cmplx_rep='AbsAng', vfname='Unknown'):
    if projection == 'orthographic':
        #Fix check for theta>pi/2
        #Plot hemisphere theta<pi/2
        UHmask = theta_rad>math.pi/2
        E_th = numpy.ma.array(E_th, mask=UHmask)
        E_ph = numpy.ma.array(E_ph, mask=UHmask)
        x = numpy.sin(theta_rad)*numpy.cos(phi_rad)
        y = numpy.sin(theta_rad)*numpy.sin(phi_rad)
        xyNames = ('l','m')
        nom_xticks=None
    elif projection == 'azimuthal-equidistant':
        #theta_res = theta_rad[1,0]-theta_rad[0,0]
        #2D polar to cartesian conversion
        #(put in offset)
        x = theta_rad*numpy.cos(phi_rad)
        y = theta_rad*numpy.sin(phi_rad)
        xyNames = ('theta*cos(phi)','theta*sin(phi)')
        nom_xticks=None
    elif projection == 'equirectangular':
        y = numpy.rad2deg(theta_rad)
        x = numpy.rad2deg(phi_rad)
        xyNames = ('phi','theta')
        nom_xticks=[0,45,90,135,180,225,270,315,360]
    else:
        print("Unknown map projection")
        exit(1)

    if vcoord == 'Ludwig3':
        E0_c, E1_c = sph2Ludwig3(phi_rad, E_th, E_ph)
        compNames = ('E_u', 'E_v')
    elif vcoord == 'sph':
        E0_c = E_th
        E1_c = E_ph
        compNames = ('E_theta', 'E_phi')
    elif vcoord == 'circ':
        E0_c = (E_th+1j*E_ph)/math.sqrt(2)
        E1_c = (E_th-1j*E_ph)/math.sqrt(2)
        compNames = ('LCP', 'RCP')
    else:
        print("Unknown vector component coord sys")
        exit(1)
    if cmplx_rep=='ReIm':
        cmpopname_r0, cmpopname_r1= 'Re', 'Im'
        E0_r0, E0_r1 = numpy.real(E0_c), numpy.imag(E0_c)
        E1_r0, E1_r1 = numpy.real(E1_c), numpy.imag(E1_c)
    elif cmplx_rep=='AbsAng':
        cmpopname_r0, cmpopname_r1= 'Abs', 'Arg'
        E0_r0, E0_r1 = numpy.absolute(E0_c), numpy.rad2deg(numpy.angle(E0_c))
        E1_r0, E1_r1 = numpy.absolute(E1_c), numpy.rad2deg(numpy.angle(E1_c))
    
    fig = plt.figure()
    fig.suptitle(vfname+' @ '+str(freq/1e6)+' MHz'+', '
                 +'projection: '+projection)
    
    ax = plt.subplot(221,polar=False)
    Z221 = E0_r0
    plt.pcolormesh(x, y, Z221)
    if nom_xticks is not None: plt.xticks(nom_xticks)
    ax.set_title(cmpopname_r0+'('+compNames[0]+')')
    
    plt.xlabel(xyNames[0])
    plt.ylabel(xyNames[1])
    plt.grid()
    plt.colorbar()
    ax.invert_yaxis()
    
    ax = plt.subplot(222, polar=False)
    Z222 = E0_r1
    plt.pcolormesh(x, y, Z222)
    if nom_xticks is not None: plt.xticks(nom_xticks)
    ax.set_title(cmpopname_r1+'('+compNames[0]+') @ '+str(freq/1e6)+' MHz')
    plt.xlabel(xyNames[0])
    plt.ylabel(xyNames[1])
    plt.grid()
    plt.colorbar()
    ax.invert_yaxis()
    
    ax = plt.subplot(223, polar=False)
    Z223 = E1_r0
    plt.pcolormesh(x, y, Z223)
    if nom_xticks is not None: plt.xticks(nom_xticks)
    ax.set_title(cmpopname_r0+'('+compNames[1]+')')
    plt.xlabel(xyNames[0])
    plt.ylabel(xyNames[1])
    plt.grid()
    plt.colorbar()
    ax.invert_yaxis()
    
    ax = plt.subplot(224, polar=False)
    Z224 = E1_r1
    plt.pcolormesh(x, y, Z224)
    if nom_xticks is not None: plt.xticks(nom_xticks)
    ax.set_title(cmpopname_r1+'('+compNames[1]+')')
    plt.xlabel(xyNames[0])
    plt.ylabel(xyNames[1])
    plt.grid()
    plt.colorbar()
    ax.invert_yaxis()
    
    plt.show()

def plotvfonsph3D(theta_rad, phi_rad, E_th, E_ph, freq=0.0,
                     vcoord='sph', projection='equirectangular'):
    PLOT3DTYPE = "quiver"
    (x, y, z) = sph2crtISO(theta_rad, phi_rad)
    from mayavi import mlab
    
    mlab.figure(1, bgcolor=(1, 1, 1), fgcolor=(0, 0, 0), size=(400, 300))
    mlab.clf()
    if PLOT3DTYPE == "MESH_RADIAL" :
        r_Et = numpy.abs(E_th)
        r_Etmx = numpy.amax(r_Et)
        mlab.mesh(r_Et*(x)-1*r_Etmx, r_Et*y, r_Et*z, scalars=r_Et)
        r_Ep = numpy.abs(E_ph)
        r_Epmx = numpy.amax(r_Eph)
        mlab.mesh(r_Ep*(x)+1*r_Epmx , r_Ep*y, r_Ep*z, scalars=r_Ep)
    elif PLOT3DTYPE == "quiver":
        ##Implement quiver plot
        s2cmat = getSph2CartTransfMatT(numpy.array([x,y,z]))
        E_r = numpy.zeros(E_th.shape)
        E_fldsph = numpy.rollaxis(numpy.array([E_r, E_ph, E_th]), 0, 3)[...,numpy.newaxis]
        E_fldcrt = numpy.rollaxis(numpy.matmul(s2cmat, E_fldsph).squeeze(), 2, 0)
        #print E_fldcrt.shape
        mlab.quiver3d(x+1.5, y, z,
                      numpy.real(E_fldcrt[0]),
                      numpy.real(E_fldcrt[1]),
                      numpy.real(E_fldcrt[2]))
        mlab.quiver3d(x-1.5, y, z,
                      numpy.imag(E_fldcrt[0]),
                      numpy.imag(E_fldcrt[1]),
                      numpy.imag(E_fldcrt[2]))              
    mlab.show()

def sph2Ludwig3(azl, EsTh, EsPh):
    """Input: an array of theta components and an array of phi components.
    Output: an array of Ludwig u components and array Ludwig v.
    Ref Ludwig1973a."""
    EsU = EsTh*numpy.sin(azl)+EsPh*numpy.cos(azl)
    EsV = EsTh*numpy.cos(azl)-EsPh*numpy.sin(azl)
    return EsU, EsV

def Ludwig32sph(azl, EsU, EsV):
    EsTh = EsU*numpy.sin(azl)+EsV*numpy.cos(azl)
    EsPh = EsU*numpy.cos(azl)-EsV*numpy.sin(azl)
    return EsTh, EsPh