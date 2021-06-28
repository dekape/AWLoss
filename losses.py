from math import floor
import torch
import torch.nn as nn
import numpy as np

class TV(nn.Module):
  def __init__(self):
    super(TV, self).__init__()

  def forward(self, x):
      """Total variation """
      reg = (torch.sum(torch.abs(x[:, :, :, :-1] - x[:, :, :, 1:])) + 
      torch.sum(torch.abs(x[:, :, :-1, :] - x[:, :, 1:, :])))
      return reg

class KLD(nn.Module):
  def __init__(self):
    super(KLD, self).__init__()

  def forward(self, mu, sigma):
      """Kl Divergence """
      return (sigma**2 + mu**2 - torch.log(sigma) - 1/2).sum()
      

class SingleAWILoss1D(nn.Module):
  def __init__(self):
    super(SingleAWILoss1D, self).__init__()
    self.D = None
    self.D_t = None
    self.v = None

  def make_toeplitz(self, a):
    h = a.size(1)
    A = torch.zeros((2*h-1, h))
    for i in range(h):
      A[i:i+h, i] = a[:]
    A = A.to(a.device)
    return A

  def pad_edges_to_len(self, x, length, val=0):
    total_pad = length - len(x)
    pad_lef = floor(total_pad / 2)
    pad_rig = total_pad - pad_lef
    return nn.ConstantPad1d((pad_lef, pad_rig), val)(x)

  def gaussian(self, xarr, a, std, mean):
    return a*torch.exp(-(xarr - mean)**2 / (2*std**2))

  def inv_gaussian(self, xarr, a, std, mean):
      y = self.gaussian(xarr, a, std, mean)
      y = y*(-1) + a
      return y

  def T(self, xarr, std=1.):
      dx = (xarr[-1] - xarr[0]) / (len(xarr) - 1)
      dispx = (len(xarr) % 2 - 1) / 2 
      tarr = -self.gaussian(xarr=xarr, a=1.0, std=std, mean=dx*dispx)
      tarr = tarr + torch.max(torch.abs(tarr))
      tarr = tarr / torch.max(torch.abs(tarr))
      return  tarr

  def norm(self, A):
    return torch.sqrt(torch.sum((A)**2))
    
  def forward(self, recon, target, alpha=0., epsilon=0., std=1.):
    recon, target = recon.flatten(start_dim=1), target.flatten(start_dim=1)

    if self.D is None:
      self.D = self.make_toeplitz(target)
      self.D_t = (self.D).T
      self.v = self.D_t @ self.D
      self.v = self.v + torch.diag(alpha*torch.diagonal(self.v) + epsilon)
      self.v = torch.inverse(self.v)
    
    recon = self.pad_edges_to_len(recon, self.D_t.shape[0])
    v = self.v @ (self.D_t @ recon[0])
    T = self.T(torch.linspace(-10., 10., v.size(0), requires_grad=True), std).to(target.device)
    f = 0.5 * self.norm(T * v) / self.norm(v) 
    return f, v, T


class SingleAWILoss2D(nn.Module):
    def __init__(self):
        super(SingleAWILoss2D, self).__init__()
        self.Z = None
        self.Z_t = None
        self.v = None
     
    def make_toeplitz(self, a):
        "Makes toeplitz matrix of a vector A"
        h = len(a)
        A = torch.zeros((2*h -1, h))
        for i in range(h):
            A[i:i+h, i] = a[:]
        A = A.to(a.device)
        return A    
    
    def make_doubly_block(self, X):
        """Makes Doubly Blocked Toeplitz of a matrix X"""
        
        r_block = 2 * X.shape[1] -1                       # each row will have a toeplitz matrix of rowsize 2*X.shape[1]
        c_block = X.shape[1]                              # each row will have a toeplitz matrix of colsize X.shape[1]
        n_blocks = X.shape[0]                             # how many rows / number of blocks
        r = 2*(n_blocks * r_block) -1*r_block             # total number of rows in doubly blocked toeplitz
        c = n_blocks * c_block                            # total number of cols in doubly blocked toeplitz
        
        Z = torch.zeros(r, c, device=X.device)
        for i in range(X.shape[0]):
            row_toeplitz = self.make_toeplitz(X[i])
            for j in range(n_blocks):
                ridx = (i+j)*r_block
                cidx = j*c_block
                Z[ridx:ridx+r_block, cidx:cidx+c_block] = row_toeplitz[:, :]
        return Z    
    
    
    def pad_edges_to_shape(self, x, shape, val=0):
        pad_top, pad_lef = floor((shape[0] - x.shape[0])/2), floor((shape[1] - x.shape[1])/2)
        pad_bot, pad_rig = shape[0] - x.shape[0] - pad_top, shape[1] - x.shape[1] - pad_lef
        return nn.ConstantPad2d((pad_lef, pad_rig, pad_top, pad_bot), val)(x)
    
    
    def gauss2d(self, x=0, y=0, mx=0, my=0, sx=1., sy=1., a=100.):
        return a / (2. * np.pi * sx * sy) * torch.exp(-((x - mx)**2. / (2. * sx**2.) + (y - my)**2. / (2. * sy**2.)))
    

    def T2D(self, shape, stdx=1., stdy=1., device="cpu"):
        xarr = torch.linspace(-10., 10., shape[0], requires_grad=True, device=device)
        yarr = torch.linspace(-10., 10., shape[1], requires_grad=True, device=device)
        xx, yy = torch.meshgrid(xarr, yarr)

        # Adjust the location of the zero-lag of the T function to match the location of the expected delta
        dispx, dispy = (len(xarr) % 2 - 1) / 2, (len(yarr) % 2 - 1) / 2

        dx, dy = (xarr[-1] - xarr[0]) / (len(xarr) - 1), (yarr[-1] - yarr[0]) / (len(yarr) - 1)
        # dx, dy = 0, 0
        tarr = -self.gauss2d(xx, yy, mx=dx*dispx, my=dy*dispy, sx=stdx, sy=stdy, a=1.)
        tarr = tarr + torch.max(torch.abs(tarr))
        tarr = tarr / torch.max(torch.abs(tarr)) # normalise amplitude of T
        return tarr.to(device)
    
    def norm(self, A):
        return torch.sqrt(torch.sum((A)**2))

    
    def forward(self, recon, target, alpha=0, epsilon=0, std=1.):
        """
        g = || P*W - D ||^2
        g = || Zw - d ||^2
        dgdw = Z^T (Zw - d)
        dgdw --> 0 : w = (Z^T @ Z)^(-1) @ Z^T @ d 

        To stabilise the matrix inversion, an amount is added to the diagonal of (Z^T @ Z)
        based on alpha and epsilon values such that the inverted matrix is 
        (Z^T @ Z) + alpha*diagonal(Z^T @ Z) + epsilon
        
        Working to minimise || P*W - D ||^2 where P is the reconstructed image convolved with a 2D kernel W, 
        D is the original/target image, and optimisation aims to force W to be an identity kernel. 
        (https://en.wikipedia.org/wiki/Kernel_(image_processing))
        
        P, D and W here in the code assumed to be single channel and numerically take form of a 2D matrix.
        
        Convolving P with W (or W with P) is equivalent to the matrix vector multiplication Zd where Z is the 
        doubly block toeplitz of the reconstructed image P and w is the flattened array of the 2D kernel W. 
        (https://stackoverflow.com/questions/16798888/2-d-convolution-as-a-matrix-matrix-multiplication)
        
        Therefore, the system is equivalent to solving || Zw - d ||^2, and the solution to w is given by
        w = (Z^T @ Z)^(-1) @ Z^T @ d 
        
        Finally, the function T is an inverse multivariate gaussian in a 2D space to reward when the kernel W is close
        to the identity kernel, and penalise otherwise.
        The value std controls the standard deviation (the spread) of T in both directions and the value a its amplitude
      
        This function applies the reverse AWI formulation
        
        """
        target, recon = target.squeeze(0).squeeze(0), recon.squeeze(0).squeeze(0)

        if self.Z is None:
            self.Z = self.make_doubly_block(target)
            self.Z_t = (self.Z).T        
            self.v = self.Z_t @ self.Z
            self.v = self.v + torch.diag(alpha*torch.diagonal(self.v)+epsilon) # stabilise diagonals for matrix inversion
            self.v = torch.inverse(self.v)
        
        recon_padded = self.pad_edges_to_shape(recon, (2*recon.shape[0] - 1, 2*recon.shape[1] - 1))   
        
        v = self.v @ self.Z_t @ recon_padded.flatten(start_dim=0)

        T = self.T2D(shape=recon.shape, stdx=std, stdy=std, device=recon.device)
        
        f = 0.5 * self.norm(T.flatten()* v) / self.norm(v)
        return f, v, T


class AWLoss1D(nn.Module):
  def __init__(self, alpha=0., epsilon=0., std=1., reduction="sum", return_filters=False) :
    super(AWLoss1D, self).__init__()
    self.alpha = alpha
    self.epsilon = epsilon
    self.std = std
    self.return_filters = return_filters

    if reduction=="mean" or reduction=="sum":
      self.reduction = reduction
    else:
      raise ValueError

  def make_toeplitz(self, a):
    h = a.size(0)
    A = torch.zeros((2*h-1, h), device=a.device)
    for i in range(h):
      A[i:i+h, i] = a[:]
    A = A.to(a.device)
    return A

  def pad_edges_to_len(self, x, length, val=0):
    total_pad = length - len(x)
    pad_lef = floor(total_pad / 2)
    pad_rig = total_pad - pad_lef
    return nn.ConstantPad1d((pad_lef, pad_rig), val)(x)

  def gaussian(self, xarr, a, std, mean):
    return a*torch.exp(-(xarr - mean)**2 / (2*std**2))

  def inv_gaussian(self, xarr, a, std, mean):
      y = self.gaussian(xarr, a, std, mean)
      y = y*(-1) + a
      return y

  def T(self, xarr, std=1.):
      dx = (xarr[-1] - xarr[0]) / (len(xarr) - 1)
      dispx = (len(xarr) % 2 - 1) / 2 
      tarr = -self.gaussian(xarr=xarr, a=1.0, std=std, mean=dx*dispx)
      tarr = tarr + torch.max(torch.abs(tarr))
      tarr = tarr / torch.max(torch.abs(tarr))
      return  tarr

  def norm(self, A):
    return torch.sqrt(torch.sum(A**2))
    
  def forward(self, recon, target):
    assert recon.shape == target.shape
    recon, target = recon.flatten(start_dim=1), target.flatten(start_dim=1)
    
    f = 0
    T = self.T(torch.linspace(-10., 10., recon.size(1), requires_grad=True), self.std).to(recon.device)
    v_all = torch.zeros_like(recon) if self.return_filters else None


    ## COULD BE VECTORISED? This loop treats every image in batch as a "separate" sample, channels are flattened
    for i in range(recon.size(0)):
      D = self.make_toeplitz(target[i])
      D_t = D.T
      v = D.T @ D
      v = v + torch.diag(self.alpha*torch.diagonal(v) + self.epsilon)
      v = torch.inverse(v)
      v = v @ (D_t @ self.pad_edges_to_len(recon[i], D_t.shape[1]))
      # v = (v - v.mean()) / v.std()
      f = f + 0.5 * self.norm(T * v) / self.norm(v)

      if self.return_filters: v_all[i] = v[:]
    
    if self.reduction == "mean":
      f = f / recon.size(0)

#     T = np.asarray(np.concatenate((np.flip(np.log(np.linspace(2,1000,(int((P-1)/2))))),np.array([0]),
# np.log(np.linspace(2,1000,(int((P-1)/2)))))), dtype=np.float32)
      
    return (f, v_all, T) if self.return_filters else f


class AWLoss2D(nn.Module):
    def __init__(self, alpha=0., epsilon=0., std=1., reduction="sum", return_filters=False):
        super(AWLoss2D, self).__init__()
        self.alpha = alpha
        self.epsilon = epsilon
        self.std = std
        self.return_filters = return_filters
        if reduction=="mean" or reduction=="sum":
          self.reduction = reduction
        else:
          raise ValueError
     
    def make_toeplitz(self, a):
        "Makes toeplitz matrix of a vector A"
        h = len(a)
        A = torch.zeros((2*h -1, h))
        for i in range(h):
            A[i:i+h, i] = a[:]
        A = A.to(a.device)
        return A    
    
    def make_doubly_block(self, X):
        """Makes Doubly Blocked Toeplitz of a matrix X [r, c]"""
        
        r_block = 2 * X.shape[1] -1                       # each row will have a toeplitz matrix of rowsize 2*X.shape[1]
        c_block = X.shape[1]                              # each row will have a toeplitz matrix of colsize X.shape[1]
        n_blocks = X.shape[0]                             # how many rows / number of blocks
        r = 2*(n_blocks * r_block) -1*r_block             # total number of rows in doubly blocked toeplitz
        c = n_blocks * c_block                            # total number of cols in doubly blocked toeplitz
        
        Z = torch.zeros(r, c, device=X.device)
        for i in range(X.shape[0]):
            row_toeplitz = self.make_toeplitz(X[i])
            for j in range(n_blocks):
                ridx = (i+j)*r_block
                cidx = j*c_block
                Z[ridx:ridx+r_block, cidx:cidx+c_block] = row_toeplitz[:, :]
        return Z    
    
    
    def pad_edges_to_shape(self, x, shape, val=0):
        pad_top, pad_lef = floor((shape[0] - x.shape[0])/2), floor((shape[1] - x.shape[1])/2)
        pad_bot, pad_rig = shape[0] - x.shape[0] - pad_top, shape[1] - x.shape[1] - pad_lef
        return nn.ConstantPad2d((pad_lef, pad_rig, pad_top, pad_bot), val)(x)
    
    
    def gauss2d(self, x=0, y=0, mx=0, my=0, sx=1., sy=1., a=100.):
        return a / (2. * np.pi * sx * sy) * torch.exp(-((x - mx)**2. / (2. * sx**2.) + (y - my)**2. / (2. * sy**2.)))
    

    def T2D(self, shape, stdx=1., stdy=1., device="cpu"):
        xarr = torch.linspace(-10., 10., shape[0], requires_grad=True, device=device)
        yarr = torch.linspace(-10., 10., shape[1], requires_grad=True, device=device)
        xx, yy = torch.meshgrid(xarr, yarr)

        # Adjust the location of the zero-lag of the T function to match the location of the expected delta spike
        dispx, dispy = (len(xarr) % 2 - 1) / 2, (len(yarr) % 2 - 1) / 2
        dx, dy = (xarr[-1] - xarr[0]) / (len(xarr) - 1), (yarr[-1] - yarr[0]) / (len(yarr) - 1)

        tarr = -self.gauss2d(xx, yy, mx=dx*dispx, my=dy*dispy, sx=stdx, sy=stdy, a=1.)
        tarr = tarr + torch.max(torch.abs(tarr))
        tarr = tarr / torch.max(torch.abs(tarr)) # normalise amplitude of T
        return tarr.to(device)
    
    def norm(self, A):
        return torch.sqrt(torch.sum((A)**2))

    
    def forward(self, recon, target):
        """
        g = || P*W - D ||^2
        g = || Zw - d ||^2
        dgdw = Z^T (Zw - d)
        dgdw --> 0 : w = (Z^T @ Z)^(-1) @ Z^T @ d 

        To stabilise the matrix inversion, an amount is added to the diagonal of (Z^T @ Z)
        based on alpha and epsilon values such that the inverted matrix is 
        (Z^T @ Z) + alpha*diagonal(Z^T @ Z) + epsilon
        
        Working to minimise || P*W - D ||^2 where P is the reconstructed image convolved with a 2D kernel W, 
        D is the original/target image, and optimisation aims to force W to be an identity kernel. 
        (https://en.wikipedia.org/wiki/Kernel_(image_processing))
        
        P, D and W here in the code assumed to be single channel and numerically take form of a 2D matrix.
        
        Convolving P with W (or W with P) is equivalent to the matrix vector multiplication Zd where Z is the 
        doubly block toeplitz of the reconstructed image P and w is the flattened array of the 2D kernel W. 
        (https://stackoverflow.com/questions/16798888/2-d-convolution-as-a-matrix-matrix-multiplication)
        
        Therefore, the system is equivalent to solving || Zw - d ||^2, and the solution to w is given by
        w = (Z^T @ Z)^(-1) @ Z^T @ d 
        
        Finally, the function T is an inverse multivariate gaussian in a 2D space to reward when the kernel W is close
        to the identity kernel, and penalise otherwise.
        The value std controls the standard deviation (the spread) of T in both directions and the value a its amplitude
      
        This function applies the reverse AWI formulation
        
        """
        assert target.shape == recon.shape

        f = 0
        T = self.T2D(shape=recon.shape[2:], stdx=self.std, stdy=self.std, device=recon.device)
        if self.return_filters: v_all = torch.zeros_like(recon.squeeze(0)) # one filter per image 

        ## COULD BE VECTORISED? This loop treats every image in batch and every channel of each image as a "separate" sample
        bs, nc = recon.size(0), recon.size(1)
        for i in range(bs): 
          for j in range(nc):
            Z = self.make_doubly_block(target[i][j])
            Z_t = Z.T        
            v = Z_t @ Z
            v = v + torch.diag(self.alpha*torch.diagonal(v)+self.epsilon) # stabilise diagonals for matrix inversion
            v = torch.inverse(v) ## COULD BE OPTIMISED?
            v = v @ (Z_t @ self.pad_edges_to_shape(recon[i][j], (2*recon.shape[2] - 1, 2*recon.shape[3] - 1)).flatten(start_dim=0))
            f = f + 0.5 * self.norm(T.flatten()* v) / self.norm(v)
            if self.return_filters: v_all[i] += v[:].view(recon.shape[2:]) / nc # returned filter is averaged in channel dimension, note that this average does not affect the functional computation
        
        if self.reduction=="mean":
          f = f / (bs * nc)
        return (f, v_all, T) if self.return_filters else f
