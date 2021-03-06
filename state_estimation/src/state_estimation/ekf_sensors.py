import rospy
import math
import numpy as np
import scipy.linalg

import autograd.numpy as np  # Thinly-wrapped numpy
from autograd import grad, jacobian, elementwise_grad

from geometry_msgs.msg import Point, Vector3, Quaternion
from sensor_msgs.msg import Imu, FluidPressure

from aquadrone_msgs.msg import SubState, MotorControls

from state_estimation.ekf_indices import IDx as IDx

class BaseSensorListener(object):
    # https://en.wikipedia.org/wiki/Extended_Kalman_filter

    #
    # Functions Common for Each Sensor; No need to re-implement
    #

    def __init__(self):
        self.last_time = rospy.Time.now().to_sec()
        self.calc_H = jacobian(self.state_to_measurement_h)

    def is_valid(self):
        return rospy.Time.now().to_sec() - self.last_time < self.get_timeout_sec()

    def get_H(self, x, u):
        # Jacobian of measurement wrt state (as calculated by get_measurement_z)
        H = self.calc_H(x, u)
        H = np.reshape(H, (self.get_p(), x.shape[0]))
        return H

    #
    # Functions Required for Each Sensor; Implement
    #

    def get_timeout_sec(self):
        # Amount of time to use old measurements for
        raise NotImplementedError

    def get_p(self):
        # Number of elements in measurement vector
        raise NotImplementedError

    def get_measurement_z(self):
        # Actual measurement from the sensor
        raise NotImplementedError

    def get_R(self):
        # Uncertainty matrix of measurements
        raise NotImplementedError

    def state_to_measurement_h(self, x, u):
        # Calculate expected sensor readings from current state and inputs
        # Needs to be autograd-able
        raise NotImplementedError



class PressureSensorListener(BaseSensorListener):
    def __init__(self):
        super(PressureSensorListener, self).__init__()
        self.depth_sub = rospy.Subscriber("aquadrone/out/pressure", FluidPressure, self.depth_cb)

        self.z = 0
        self.var = 1

        self.pressure_offset = 100.0
        self.g = 9.8

    def get_timeout_sec(self):
        return 0.1

    def get_p(self):
        return 1

    def get_measurement_z(self):
        vec = np.zeros((1,1))
        vec[0] = self.z
        return vec

    def get_R(self):
        # Variance of measurements
        var = np.zeros((1,1))
        var[0,0] = self.var
        return var

    def state_to_measurement_h(self, x, u):
        return x[IDx.Pz]

    def depth_cb(self, msg):
        press = msg.fluid_pressure
        var = msg.variance

        self.z = -self.pressure_to_depth(press)
        self.var = var / self.g
        self.last_time = rospy.Time.now().to_sec()

    def pressure_to_depth(self, press):
        return (press - self.pressure_offset) / self.g


class IMUSensorListener(BaseSensorListener):
    def __init__(self):
        super(IMUSensorListener, self).__init__()
        self.imu_sub = rospy.Subscriber("aquadrone/out/imu", Imu, self.imu_cb)

        self.accel = np.array([0, 0, 0])
        self.accel_var = np.array([1, 1, 1])

        self.orientation = np.array([1, 0, 0, 0])
        self.orientation_var = np.array([1, 1, 1, 1])

        self.ang_vel = np.array([0, 0, 0])
        self.ang_vel_variance = np.array([1, 1, 1])

    def get_timeout_sec(self):
        return 0.1

    def get_p(self):
        # 4 orientation elements in quaternion form
        # 3 angular velocities
        # 3 linear accelerations
        return 10

    def get_measurement_z(self):
        vec = np.zeros((self.get_p(),1))

        for i in range(0, 3):
            vec[i] = self.accel[i]

        for i in range(0, 4):
            vec[i+3] = self.orientation[i]

        for i in range(0, 3):
            vec[i+7] = self.ang_vel[i]

        return vec

    def get_R(self):
        # Variance of measurements
        var = np.zeros((self.get_p(),self.get_p()))
        for i in range(0, 3):
            var[i,i] = self.accel_var[i]
        for i in range(0, 4):
            var[i+3,i+3] = self.orientation_var[i]
        for i in range(0, 3):
            var[i+7, i+7] = self.ang_vel_variance[i]
        return var

    def state_to_measurement_h(self, x, u):
        z =  np.array( [ x[IDx.Accx],
                         x[IDx.Accy],
                         x[IDx.Accz] + 9.81,
                         x[IDx.Ow],
                         x[IDx.Ox],
                         x[IDx.Oy],
                         x[IDx.Oz],
                         x[IDx.Ax],
                         x[IDx.Ay],
                         x[IDx.Az] ])
        #z.shape = (4,1)
        return z

    def imu_cb(self, msg):

        self.accel = np.array([msg.linear_acceleration.x,
                               msg.linear_acceleration.y,
                               msg.linear_acceleration.z])[np.newaxis]
        self.accel.shape = (3, 1)

        self.accel_var = np.array([msg.linear_acceleration_covariance[0],
                                   msg.linear_acceleration_covariance[0],
                                   msg.linear_acceleration_covariance[0]])

        self.orientation = np.array([ msg.orientation.w,
                                      msg.orientation.x,
                                      msg.orientation.y,
                                      msg.orientation.z ])[np.newaxis]
        self.orientation.shape = (4, 1)

        # Need to verify what our onboard sensor reports
        # Keep as this as an initial estimate
        self.orientation_var = np.array([ msg.orientation_covariance[0],
                                          msg.orientation_covariance[0],
                                          msg.orientation_covariance[0],
                                          msg.orientation_covariance[0] ])
        

        self.ang_vel = np.array([ msg.angular_velocity.x,
                                  msg.angular_velocity.y,
                                  msg.angular_velocity.z ])[np.newaxis]
        self.ang_vel.shape = (3,1)

        self.ang_vel_variance = np.array([msg.angular_velocity_covariance[0],
                                          msg.angular_velocity_covariance[4],
                                          msg.angular_velocity_covariance[8]])

        self.last_time = rospy.Time.now().to_sec()
